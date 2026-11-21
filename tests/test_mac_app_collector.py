import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess, TimeoutExpired

from ai_usage_widget import cli
from ai_usage_widget import mac_app_collector as collector
from ai_usage_widget.antigravity_limits_provider import AntigravityLimitsProvider, AntigravityProviderError
from ai_usage_widget.limits_runtime import load_fixture_providers


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

    def test_usage_replaces_legacy_ip_labels_without_changing_pairing_or_release_metadata(self):
        device = self.root / 'collector/device.json'
        current = self.root / 'current'
        current.mkdir()
        revision = 'a' * 40
        (current / 'release.json').write_text(json.dumps({'revision': revision}))
        config = {
            **collector.read_json(device), 'schema_version': 1, 'source_id': 'paired-device',
            'platform': 'darwin', 'timezone': 'Africa/Abidjan', 'os_user': 'test-user',
            'outbox': {'enabled': True, 'path': str(self.root / 'collector/outbox.sqlite')},
        }
        with (
            patch.dict(os.environ),
            patch.object(collector.sys, 'platform', 'darwin'),
            patch.object(collector.subprocess, 'run', return_value=CompletedProcess([], 0, 'Test-Mac\n', '')) as scutil,
            patch.object(cli, 'DevicePusher') as pusher,
        ):
            pusher.return_value.push.return_value = {'success': True, 'delivered': True}
            for address in ('192.0.2.7', '2001:db8::7'):
                with self.subTest(address=address):
                    original = json.dumps({**config, 'machine': address, 'host': address}).encode()
                    device.write_bytes(original)
                    self.assertEqual(collector.run_job(self.root, 'usage'), 0)
                    effective = pusher.call_args.args[0]
                    self.assertEqual((effective.machine, effective.host), ('Test-Mac', 'Test-Mac'))
                    self.assertEqual(effective.source_id, config['source_id'])
                    self.assertEqual(effective.timezone, config['timezone'])
                    self.assertEqual(str(effective.outbox.path), config['outbox']['path'])
                    self.assertEqual(os.environ['CUSTOM_TOKEN'], 'private-test-token')
                    self.assertEqual(os.environ['AI_USAGE_BUILD_SHA'], revision)
                    self.assertEqual(device.read_bytes(), original)
            self.assertEqual(scutil.call_args.args[0], ['/usr/sbin/scutil', '--get', 'LocalHostName'])

    def test_usage_preserves_explicit_or_unresolvable_device_names(self):
        device = self.root / 'collector/device.json'
        config = {**collector.read_json(device), 'schema_version': 1}
        resolved = CompletedProcess([], 0, 'Test-Mac\n', '')
        for platform, machine, host, expected_lookup, result in (
            ('darwin', 'Named Mac', '192.0.2.5', False, resolved),
            ('darwin', '192.0.2.5', 'separate.local', False, resolved),
            ('linux', '192.0.2.5', '192.0.2.5', False, resolved),
            ('darwin', '192.0.2.5', '192.0.2.5', True, TimeoutExpired('scutil', 2)),
            ('darwin', '192.0.2.5', '192.0.2.5', True, CompletedProcess([], 0, '192.0.2.6\n', '')),
        ):
            with self.subTest(platform=platform, machine=machine, host=host, result=result):
                original = json.dumps({**config, 'platform': platform, 'machine': machine, 'host': host}).encode()
                device.write_bytes(original)
                with (
                    patch.object(collector.sys, 'platform', 'darwin'),
                    patch.object(collector.subprocess, 'run', side_effect=result if isinstance(result, Exception) else None, return_value=result) as scutil,
                    patch.object(collector, 'cli_main', side_effect=lambda _: (print('{"success":true,"delivered":true}'), 0)[1]) as run,
                ):
                    self.assertEqual(collector.run_job(self.root, 'usage'), 0)
                self.assertEqual(run.call_args.args[0][2], str(device))
                self.assertEqual(scutil.called, expected_lookup)
                self.assertEqual(device.read_bytes(), original)

    def test_offline_auto_discovered_antigravity_keeps_upgrade_healthy_without_rewriting_limits(self):
        from ai_usage_widget.upgrade_apply import mac_health
        from ai_usage_widget.version_contract import COLLECTOR_VERSION

        device = self.root / 'collector/device.json'
        device.write_text(json.dumps({**collector.read_json(device), 'source_id': 'mac-test'}))
        (self.root / '.gemini/antigravity').mkdir(parents=True)
        limits = self.root / 'collector/limits.json'
        original = b'{"timezone":"Asia/Shanghai","providers":[]}\n'
        limits.write_bytes(original)
        summaries = self.root / 'summaries'
        summaries.mkdir()
        (summaries / 'today-offset0.json').write_text('{"sources":[{}]}')
        codex = load_fixture_providers(str(Path(__file__).parent / 'fixtures/limits_runtime_fixture.json'))['codex']

        with (
            patch.object(collector.Path, 'home', return_value=self.root),
            patch.object(AntigravityLimitsProvider, 'collect', side_effect=AntigravityProviderError('provider_unavailable', 'offline')),
            patch.object(cli.CodexWhamProvider, 'collect', return_value=codex.collect()),
            patch('ai_usage_widget.limits_runtime._default_now', return_value='2026-06-03T10:02:00+08:00'),
            patch.object(cli, '_outbox_config_for_push_limits', return_value=None),
            patch.object(cli, 'push_limits_payload', return_value={'success': True, 'windows_written': 1}) as push,
        ):
            configured_codex = json.dumps({'timezone': 'Asia/Shanghai', 'providers': [
                {'provider': 'codex', 'source_id': 'mac-test-codex', 'auth_file': '/test/codex/auth.json'},
            ]}).encode()
            for saved in (original, configured_codex, None):
                with self.subTest(saved=saved):
                    if saved is None:
                        limits.unlink()
                    else:
                        limits.write_bytes(saved)
                    code = collector.run_job(self.root, 'limits')
                    self.assertEqual(code, collector.LIMITS_DELIVERED_PARTIAL)
                    windows = push.call_args.args[2]['windows']
                    window = windows[-1]
                    self.assertEqual((window['provider'], window['source_id'], window['status']), ('antigravity', 'mac-test', 'provider_failed'))
                    self.assertEqual(window['confidence'], 'missing')
                    self.assertFalse(window['official'])
                    if saved == configured_codex:
                        self.assertTrue(windows[0]['official'])
                    if saved is None:
                        self.assertFalse(limits.exists())
                    else:
                        self.assertEqual(limits.read_bytes(), saved)
                    collector.write_status(self.root, {'usage': collector.job_status('usage', 0), 'limits': collector.job_status('limits', code)})
                    report = collector.read_json(self.root / 'collector/status.json')
                    self.assertTrue(report['limits']['partial'])
                    self.assertTrue(mac_health(self.root, {'collector_version': COLLECTOR_VERSION}, 0))

    def test_explicit_antigravity_offline_remains_a_failed_job(self):
        device = self.root / 'collector/device.json'
        device.write_text(json.dumps({**collector.read_json(device), 'source_id': 'mac-test'}))
        (self.root / '.gemini/antigravity').mkdir(parents=True)
        (self.root / 'collector/limits.json').write_text(json.dumps({
            'timezone': 'Asia/Shanghai',
            'providers': [{'provider': 'antigravity', 'source_id': 'explicit-ag'}],
        }))
        with (
            patch.object(collector.Path, 'home', return_value=self.root),
            patch.object(AntigravityLimitsProvider, 'collect', side_effect=AntigravityProviderError('provider_unavailable', 'offline')),
            patch.object(cli, '_outbox_config_for_push_limits', return_value=None),
            patch.object(cli, 'push_limits_payload', return_value={'success': True, 'windows_written': 1}),
        ):
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

    def test_explicit_antigravity_offline_with_delivered_codex_keeps_upgrade_healthy(self):
        from ai_usage_widget.upgrade_apply import mac_health
        from ai_usage_widget.version_contract import COLLECTOR_VERSION

        device = self.root / 'collector/device.json'
        device.write_text(json.dumps({**collector.read_json(device), 'source_id': 'mac-test'}))
        limits = self.root / 'collector/limits.json'
        original = json.dumps({'timezone': 'Asia/Shanghai', 'providers': [
            {'provider': 'antigravity', 'source_id': 'configured-ag'},
            {'provider': 'codex', 'source_id': 'mac-test-codex', 'auth_file': '/test/codex/auth.json'},
        ]}).encode()
        limits.write_bytes(original)
        summaries = self.root / 'summaries'
        summaries.mkdir()
        (summaries / 'today-offset0.json').write_text('{"sources":[{}]}')
        codex = load_fixture_providers(str(Path(__file__).parent / 'fixtures/limits_runtime_fixture.json'))['codex']

        with (
            patch.object(collector.Path, 'home', return_value=self.root),
            patch.object(AntigravityLimitsProvider, 'collect', side_effect=AntigravityProviderError('provider_unavailable', 'offline')),
            patch.object(cli.CodexWhamProvider, 'collect', return_value=codex.collect()),
            patch('ai_usage_widget.limits_runtime._default_now', return_value='2026-06-03T10:02:00+08:00'),
            patch.object(cli, '_outbox_config_for_push_limits', return_value=None),
            patch.object(cli, 'push_limits_payload', return_value={'success': True, 'windows_written': 2}) as push,
        ):
            code = collector.run_job(self.root, 'limits')

        self.assertEqual(code, collector.LIMITS_DELIVERED_PARTIAL)
        windows = {window['source_id']: window for window in push.call_args.args[2]['windows']}
        self.assertEqual(windows['configured-ag']['status'], 'provider_failed')
        self.assertFalse(windows['configured-ag']['official'])
        self.assertTrue(windows['mac-test-codex']['official'])
        self.assertEqual(limits.read_bytes(), original)
        collector.write_status(self.root, {'usage': collector.job_status('usage', 0), 'limits': collector.job_status('limits', code)})
        self.assertEqual(collector.read_json(self.root / 'collector/status.json')['limits'],
                         {'success': True, 'exit_code': collector.LIMITS_DELIVERED_PARTIAL, 'partial': True})
        self.assertTrue(mac_health(self.root, {'collector_version': COLLECTOR_VERSION}, 0))

    def test_explicit_antigravity_does_not_hide_provider_or_delivery_errors(self):
        device = self.root / 'collector/device.json'
        device.write_text(json.dumps({**collector.read_json(device), 'source_id': 'mac-test'}))
        limits = self.root / 'collector/limits.json'
        limits.write_text(json.dumps({'timezone': 'Asia/Shanghai', 'providers': [
            {'provider': 'antigravity', 'source_id': 'configured-ag'},
            {'provider': 'codex', 'source_id': 'mac-test-codex', 'auth_file': '/test/codex/auth.json'},
        ]}))
        codex = load_fixture_providers(str(Path(__file__).parent / 'fixtures/limits_runtime_fixture.json'))['codex']

        with (
            patch.object(collector.Path, 'home', return_value=self.root),
            patch.object(AntigravityLimitsProvider, 'collect') as antigravity,
            patch.object(cli.CodexWhamProvider, 'collect', return_value=codex.collect()) as codex_collect,
            patch('ai_usage_widget.limits_runtime._default_now', return_value='2026-06-03T10:02:00+08:00'),
            patch.object(cli, '_outbox_config_for_push_limits', return_value=None) as outbox,
            patch.object(cli, 'push_limits_payload', return_value={'success': True, 'windows_written': 2}) as push,
            patch.object(cli, 'deliver_limits_payload', return_value={'delivered': False, 'queued': True}),
        ):
            antigravity.side_effect = AntigravityProviderError('unauthorized', 'denied')
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

            antigravity.side_effect = AntigravityProviderError('provider_unavailable', 'offline')
            codex_collect.side_effect = ValueError('unavailable')
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

            codex_collect.side_effect = None
            push.side_effect = ValueError('delivery failed')
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

            outbox.return_value = object()
            code = collector.run_job(self.root, 'limits')
            self.assertFalse(collector.job_status('limits', code)['success'])

            limits.write_text('{"timezone":"Asia/Shanghai","providers":[{"provider":"antigravity","enabled":"true"}]}')
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

    def test_offline_discovery_does_not_hide_required_provider_or_delivery_failure(self):
        device = self.root / 'collector/device.json'
        device.write_text(json.dumps({**collector.read_json(device), 'source_id': 'mac-test'}))
        (self.root / '.gemini/antigravity').mkdir(parents=True)
        limits = self.root / 'collector/limits.json'
        limits.write_text(json.dumps({'timezone': 'Asia/Shanghai', 'providers': [
            {'provider': 'codex', 'source_id': 'mac-test-codex', 'auth_file': '/test/codex/auth.json'},
        ]}))
        with (
            patch.object(collector.Path, 'home', return_value=self.root),
            patch.object(AntigravityLimitsProvider, 'collect', side_effect=AntigravityProviderError('provider_unavailable', 'offline')),
            patch.object(cli.CodexWhamProvider, 'collect', side_effect=ValueError('unavailable')),
            patch.object(cli, '_outbox_config_for_push_limits', return_value=None),
            patch.object(cli, 'push_limits_payload', return_value={'success': True, 'windows_written': 2}) as push,
        ):
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)
            self.assertEqual(len(push.call_args.args[2]['windows']), 2)

            limits.write_text('{"timezone":"Asia/Shanghai","providers":[]}')
            push.side_effect = ValueError('delivery failed')
            self.assertEqual(collector.run_job(self.root, 'limits'), 1)

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
