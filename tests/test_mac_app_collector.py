import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget import mac_app_collector as collector


class MacAppCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'collector').mkdir()
        (self.root / 'config.json').write_text(json.dumps({'token': 'private-test-token'}))
        (self.root / 'collector/device.json').write_text(json.dumps({'server_url': 'https://example.test/ingest', 'token_env': 'CUSTOM_TOKEN'}))
        (self.root / 'collector/limits.json').write_text('{}')
        (self.root / 'collector/settings.json').write_text(json.dumps({'enabled': True}))

    def test_unconfigured_or_disabled_app_never_collects(self):
        self.assertTrue(collector.is_enabled(self.root))
        (self.root / 'collector/settings.json').write_text('{"enabled": false}')
        self.assertFalse(collector.is_enabled(self.root))
        (self.root / 'collector/settings.json').unlink()
        self.assertFalse(collector.is_enabled(self.root))

    def test_jobs_keep_device_identity_and_share_private_token_without_argv(self):
        with patch.object(collector, 'cli_main', side_effect=lambda argv: (print('{"success":true,"delivered":true}'),0)[1]) as run:
            self.assertEqual(collector.run_job(self.root, 'usage'), 0)
            usage = run.call_args.args[0]
            self.assertEqual(usage[:3], ['push', '--config', str(self.root / 'collector/device.json')])
            self.assertIn('--lock-file', usage)
            self.assertNotIn('private-test-token', ' '.join(usage))
            self.assertEqual(os.environ['CUSTOM_TOKEN'], 'private-test-token')
            self.assertEqual(collector.run_job(self.root, 'limits'), 0)
            limits = run.call_args.args[0]
            self.assertEqual(limits[0], 'push-limits')
            self.assertEqual(limits[limits.index('--url') + 1], 'https://example.test/ingest-limits')
            self.assertIn('--config', limits)
            self.assertEqual(limits[limits.index('--token-env') + 1], 'CUSTOM_TOKEN')


    def test_buffered_limits_are_not_reported_as_delivered(self):
        with patch.object(collector, 'cli_main', side_effect=lambda argv: (print('{"success":true,"delivered":false}'), 0)[1]):
            self.assertEqual(collector.run_job(self.root, 'limits'), 75)

    def test_buffered_usage_is_classified_from_stderr_without_logging_payload(self):
        import sys
        def queued(argv):
            print('{"success":false,"error_type":"outbox_queued","outbox":{"pending":1}}',file=sys.stderr)
            return 1
        with patch.object(collector,'cli_main',side_effect=queued):
            self.assertEqual(collector.run_job(self.root,'usage'),75)

    def test_missing_token_does_not_call_network_and_does_not_echo_values(self):
        (self.root / 'config.json').write_text('{}')
        with patch.object(collector, 'cli_main') as run:
            self.assertEqual(collector.run_job(self.root, 'usage'), 2)
            run.assert_not_called()

    def test_due_schedule_uses_30_minutes_and_failure_does_not_busy_retry(self):
        schedule = collector.Schedule()
        self.assertTrue(schedule.due('usage', 0))
        schedule.finished('usage', 0)
        self.assertFalse(schedule.due('usage', 1799))
        self.assertTrue(schedule.due('usage', 1800))
        self.assertTrue(schedule.due('limits', 1))

    def test_daemon_lock_prevents_second_scheduler(self):
        with collector.daemon_lock(self.root):
            with self.assertRaises(collector.AlreadyRunning):
                with collector.daemon_lock(self.root):
                    self.fail('second scheduler acquired the same lock')

    def test_status_contains_only_safe_summary_and_is_private(self):
        collector.write_status(self.root, {'usage': {'success': False, 'exit_code': 1}})
        path = self.root / 'collector/status.json'
        status = json.loads(path.read_text())
        self.assertEqual(status['usage']['exit_code'], 1)
        self.assertNotIn('private-test-token', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_timeout_terminates_entire_child_group(self):
        import subprocess
        with patch.object(collector.subprocess, 'Popen') as spawn, patch.object(collector.os, 'killpg') as kill:
            child = spawn.return_value
            child.pid = 12345
            child.wait.side_effect = [subprocess.TimeoutExpired('job', 240), 0]
            self.assertEqual(collector.execute_job(self.root, 'usage'), 124)
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            kill.assert_called_once_with(12345, collector.signal.SIGTERM)

    def test_spawn_failure_is_reported_and_does_not_crash_daemon(self):
        with patch.object(collector.subprocess, 'Popen', side_effect=OSError('sensitive test detail')):
            self.assertEqual(collector.execute_job(self.root, 'usage'), 127)

class ParentLifecycleTests(unittest.TestCase):
    def test_parent_exit_stops_worker(self):
        with patch.object(collector._STOP, 'wait', return_value=False), patch.object(collector.os, 'kill', side_effect=ProcessLookupError), patch.object(collector, 'stop') as stop:
            collector.watch_parent(424242)
            stop.assert_called_once_with(None, None)

    def test_sigterm_cancels_live_child_group_and_exits_daemon(self):
        import subprocess
        import sys
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'collector').mkdir()
            (root / 'collector/settings.json').write_text('{"enabled":true}')
            code = '''
import pathlib,subprocess,sys
from ai_usage_widget import mac_app_collector as c
root=pathlib.Path(sys.argv[1])
def command(root,job):
 return [sys.executable,'-c',"import pathlib,time,os; pathlib.Path("+repr(str(root/'child.pid'))+").write_text(str(os.getpid())); time.sleep(60)"]
c.job_command=command
raise SystemExit(c.daemon(root))
'''
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
            worker = subprocess.Popen([sys.executable,'-c',code,str(root)],env=env)
            try:
                deadline = time.monotonic()+5
                while not (root/'child.pid').exists() and time.monotonic()<deadline:
                    time.sleep(0.02)
                self.assertTrue((root/'child.pid').exists(), 'actual child never started')
                pid = int((root/'child.pid').read_text())
                worker.terminate()
                self.assertEqual(worker.wait(timeout=5),0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid,0)
            finally:
                if worker.poll() is None:
                    worker.kill(); worker.wait()
