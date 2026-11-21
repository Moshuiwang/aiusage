"""App-owned local collector. No launchd, shell sourcing or UI data aggregation."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .cli import main as cli_main
from .limits_config import ConfigError, parse_limits_config, runtime_id

INTERVAL = 1800
TIMEOUT = 240
LIMITS_DELIVERED_PARTIAL = 10
_STOP = threading.Event()
_CHILD = None


class AlreadyRunning(RuntimeError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def is_enabled(root):
    try:
        return read_json(root / 'collector/settings.json').get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return False


@contextlib.contextmanager
def daemon_lock(root):
    folder = root / 'collector'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / 'daemon.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlreadyRunning()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Schedule:
    def __init__(self):
        self.last = {}

    def due(self, job, now):
        return job not in self.last or now - self.last[job] >= INTERVAL

    def finished(self, job, now):
        self.last[job] = now


def write_status(root, status):
    from datetime import datetime, timezone
    path = root / 'collector/status.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    status['updated_at'] = datetime.now(timezone.utc).isoformat()
    from .version_contract import COLLECTOR_VERSION
    status['collector_version'] = COLLECTOR_VERSION
    temp = path.with_suffix('.tmp')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(status, handle)
    os.replace(temp, path)


@contextlib.contextmanager
def _limits_config_for_job(path, device, home):
    try:
        config = read_json(path)
    except FileNotFoundError:
        config = {'timezone': device.get('timezone') or 'Asia/Shanghai', 'providers': []}
    except (OSError, ValueError):
        config = None  # Leave explicit malformed settings for normal CLI validation.
    source_id = device.get('source_id')
    providers = config.get('providers') if isinstance(config, dict) else None
    if not isinstance(source_id, str) or not source_id or not isinstance(providers, list) or not all(isinstance(item, dict) for item in providers):
        yield str(path), None, set()
        return

    generated_claude = {
        'provider': 'claude', 'source_id': source_id + '-claude',
        'auth_file': str(home / '.claude/.credentials.json'),
    }
    changed = False
    for index, item in enumerate(providers):
        if item == generated_claude:
            providers[index] = {**item, 'cli': True}
            changed = True

    optional_source = None
    has_configured_antigravity = any(str(item.get('provider')).strip() == 'antigravity' for item in providers)
    configured_antigravity = set()
    if has_configured_antigravity:
        try:
            parsed = parse_limits_config(config)
        except ConfigError:
            pass  # Let the CLI report invalid configuration normally.
        else:
            configured_antigravity = {
                runtime_id(item) for item in parsed.enabled_providers if item.provider == 'antigravity'
            }
    used_sources = {
        str(item.get('source_id') or item.get('provider')).strip()
        for item in providers if item.get('enabled', True)
    }
    if not has_configured_antigravity and source_id not in used_sources and any(
        (home / '.gemini' / name).is_dir() for name in ('antigravity', 'antigravity-cli', 'antigravity-ide')
    ):
        # Existing credentials already own the device's source ID. Do not add
        # a new authorization scope or replace a user-configured quota source.
        providers.append({'provider': 'antigravity', 'source_id': source_id})
        optional_source = source_id
        changed = True

    if not changed:
        yield str(path), None, configured_antigravity
        return
    # A failed upgrade restores the prior bundle, not its settings files.
    # Keep auto-discovery job-local so the restored app reads identical bytes.
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as candidate:
        json.dump(config, candidate)
        candidate.flush()
        candidate.seek(0)
        yield f'/dev/fd/{candidate.fileno()}', optional_source, configured_antigravity


def _delivered_with_optional_source_offline(result, optional_source, configured_antigravity):
    if optional_source is None and not configured_antigravity:
        return False
    if result.get('delivered') is not True or result.get('success') is not False:
        return False
    providers = result['providers']
    failures = [item for item in providers if item.get('status') != 'ok']
    if len(failures) != 1 or failures[0].get('error_type') != 'provider_unavailable':
        return False
    source_id = failures[0].get('source_id')
    if optional_source is not None and source_id == optional_source:
        return True
    # An explicit source may degrade only if another source collected usable quota.
    return source_id in configured_antigravity and len(providers) > 1


def run_job(root, job):
    try:
        device_path = root / 'collector/device.json'
        device = read_json(device_path)
        token = read_json(root / 'config.json').get('token')
        if not isinstance(token, str) or not token:
            return 2
        token_env = device.get('token_env') or 'AI_USAGE_INGEST_TOKEN'
        os.environ[token_env] = token
        # LaunchServices does not inherit the user's interactive PATH.
        home = Path.home()
        os.environ['PATH'] = ':'.join([str(home / '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin',
                                       '/usr/sbin', '/sbin', '/usr/bin', '/bin',
                                       str(home / '.npm-global/bin'), os.environ.get('PATH', '')])
        output = io.StringIO()
        optional_source = None
        configured_antigravity = set()
        with contextlib.ExitStack() as resources:
            if job == 'usage':
                argv = ['push', '--config', str(device_path), '--lock-file', str(root / 'collector/usage.lock')]
            else:
                endpoint = device['server_url'].rstrip('/')
                if not endpoint.endswith('/ingest'):
                    return 2
                limits_path, optional_source, configured_antigravity = resources.enter_context(
                    _limits_config_for_job(root / 'collector/limits.json', device, home)
                )
                argv = ['push-limits', '--limits-config', limits_path,
                        '--url', endpoint[:-len('/ingest')] + '/ingest-limits', '--token-env', token_env,
                        '--config', str(device_path), '--lock-file', str(root / 'collector/limits.lock')]
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                code = cli_main(argv)
        try:
            result = json.loads(output.getvalue())
        except ValueError:
            return code or 2
        if result.get('error_type') == 'outbox_queued':
            return 75
        if code == 1 and _delivered_with_optional_source_offline(result, optional_source, configured_antigravity):
            return LIMITS_DELIVERED_PARTIAL
        if code:
            return code
        if result.get('delivered') is False:
            return 75  # safely buffered, not yet delivered
        return 0 if result.get('success') is True else 2
    except Exception:
        # Collector exceptions can contain paths and credentials; only an exit status leaves the helper.
        return 2


def job_status(job, code):
    partial = job == 'limits' and code == LIMITS_DELIVERED_PARTIAL
    status = {'success': code == 0 or partial, 'exit_code': code}
    if partial:
        status['partial'] = True
    return status


def job_command(root, job):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--root', str(root), '--job', job]
    return [sys.executable, '-m', 'ai_usage_widget.mac_app_collector', '--root', str(root), '--job', job]


def terminate_group(child):
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    except ProcessLookupError:
        pass


def execute_job(root, job):
    global _CHILD
    try:
        _CHILD = subprocess.Popen(job_command(root, job), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            return _CHILD.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            terminate_group(_CHILD)
            return 124
    except OSError:
        return 127
    finally:
        _CHILD = None


def stop(signum, frame):
    _STOP.set()
    if _CHILD is not None:
        terminate_group(_CHILD)


def watch_parent(parent_pid):
    while not _STOP.wait(5):
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            stop(None, None)
            return
        except PermissionError:
            return


def daemon(root, parent_pid=None):
    schedule = Schedule()
    status = {}
    try:
        with daemon_lock(root):
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            if parent_pid:
                threading.Thread(target=watch_parent, args=(parent_pid,), daemon=True).start()
            while not _STOP.is_set() and is_enabled(root):
                for job in ('usage', 'limits'):
                    if _STOP.is_set() or not is_enabled(root):
                        break
                    now = time.monotonic()
                    if schedule.due(job, now):
                        code = execute_job(root, job)
                        schedule.finished(job, time.monotonic())
                        status[job] = job_status(job, code)
                        write_status(root, status)
                _STOP.wait(30)
    except AlreadyRunning:
        return 0
    except Exception:
        return 2
    return 0


def main():
    if sys.argv[1:2] == ['--collector-cli']:
        return cli_main(sys.argv[2:])
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--job', choices=('usage', 'limits'))
    parser.add_argument('--parent-pid', type=int)
    args = parser.parse_args()
    if args.job:
        # CLI payloads and diagnostics stay inside the worker, never in UI or runtime logs.
        with open(os.devnull, 'w') as null, contextlib.redirect_stdout(null), contextlib.redirect_stderr(null):
            return run_job(args.root, args.job)
    return daemon(args.root, args.parent_pid)


if __name__ == '__main__':
    raise SystemExit(main())
