"""Deterministic raw inputs through the real collectors and pusher payload owner."""
import json
import sys
from datetime import datetime

from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.mswusage_codex import build_report as codex_report
from ai_usage_widget.mswusage_claude import build_report as claude_report
from ai_usage_widget.pusher import DevicePusher, _CcusageCollection, _MswusageCollection

NOW = datetime.fromisoformat('2026-09-22T12:00:00+08:00')


def collect_payloads(day='2026-09-22'):
    now = datetime.fromisoformat(f'{day}T12:00:00+08:00')
    codex_lines = [json.dumps({'type': 'session_meta', 'payload': {'id': 'model-fixture'}})]
    for minute, model, total in [(0, 'gpt-6-sol', 100), (1, 'gpt-6-luna', 200), (2, None, 50)]:
        codex_lines.extend([
            json.dumps({'type': 'turn_context', 'payload': {'model': model}}),
            json.dumps({'type': 'event_msg', 'timestamp': f'{day}T01:{minute:02}:00Z',
                'payload': {'type': 'token_count', 'info': {'last_token_usage': {
                    'input_tokens': total - 10, 'cached_input_tokens': 5, 'output_tokens': 10}}}}),
        ])
    claude_lines = [json.dumps({'type': 'assistant', 'timestamp': f'{day}T01:00:00Z',
        'message': {'id': 'fixture-claude', 'model': 'claude-opus', 'usage': {'input_tokens': 300}}})]
    codex = codex_report(codex_lines, timezone='Asia/Shanghai', now=now)
    claude = claude_report(claude_lines, timezone='Asia/Shanghai', now=now)
    payloads = []
    for source, machine, report in [('model-mac', 'mac', codex), ('model-linux', 'linux', codex)]:
        config = DeviceConfig(1, source, machine, machine, 'alice', 'darwin' if machine == 'mac' else 'linux',
                              'Asia/Shanghai', 'https://example.test/ingest')
        payload = DevicePusher(config)._build_payload(
            _CcusageCollection({}, [], None, False, None),
            _MswusageCollection(report, None, claude if machine == 'mac' else None))
        payload['observed_at'] = now.isoformat()
        payloads.append(payload)
    return payloads


if __name__ == '__main__':
    print(json.dumps(collect_payloads(sys.argv[1] if len(sys.argv) > 1 else '2026-09-22'), ensure_ascii=False, sort_keys=True))
