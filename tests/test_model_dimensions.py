import json
import unittest
from datetime import datetime

from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.mswusage_codex import build_report as codex_report
from ai_usage_widget.mswusage_claude import build_report as claude_report
from ai_usage_widget.pusher import _usage_hourly_facts_from_mswusage


NOW = datetime.fromisoformat('2026-09-22T12:00:00+08:00')


def codex_event(minute, total):
    return json.dumps({'type': 'event_msg', 'timestamp': f'2026-09-22T01:{minute:02}:00Z',
        'payload': {'type': 'token_count', 'info': {'last_token_usage': {
            'input_tokens': total - 10, 'cached_input_tokens': 5, 'output_tokens': 10}}}})


class ModelDimensionsTests(unittest.TestCase):
    def assert_conserved(self, report):
        self.assertEqual(len(report['hourly']), 1)
        for row in report['hourly'] + report['daily']:
            self.assertGreaterEqual(len(row['model_breakdowns']), 2)
            for field in ('input_tokens', 'output_tokens', 'cache_creation_tokens',
                          'cache_read_tokens', 'reasoning_output_tokens', 'total_tokens'):
                self.assertEqual(sum(m[field] for m in row['model_breakdowns']), row[field], field)

    def test_codex_model_switch_and_file_boundary_do_not_guess_history(self):
        lines = [json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-sol'}}),
                 codex_event(0, 100),
                 json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-luna'}}),
                 codex_event(1, 200), json.dumps({'type': 'mswusage_file_boundary'}),
                 codex_event(2, 50)]
        report = codex_report(lines, timezone='Asia/Shanghai', now=NOW)
        self.assert_conserved(report)
        self.assertEqual({m['model']: m['total_tokens'] for m in report['hourly'][0]['model_breakdowns']},
                         {'gpt-6-sol': 100, 'gpt-6-luna': 200, 'unknown': 50})

    def test_codex_session_and_empty_turn_context_clear_model(self):
        lines = [json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-sol'}}),
                 codex_event(0, 100), json.dumps({'type': 'session_meta', 'payload': {'id': 'next'}}),
                 codex_event(1, 50), json.dumps({'type': 'turn_context', 'payload': {}}), codex_event(2, 20)]
        report = codex_report(lines, timezone='Asia/Shanghai', now=NOW)
        self.assert_conserved(report)
        self.assertEqual({m['model']: m['total_tokens'] for m in report['hourly'][0]['model_breakdowns']},
                         {'gpt-6-sol': 100, 'unknown': 70})

    def test_claude_models_survive_dedupe_and_pusher_wire_payload(self):
        lines = []
        for n, model, total in [(1, 'claude-opus', 100), (1, 'claude-opus', 120),
                                (2, 'claude-sonnet', 200), (3, None, 50)]:
            lines.append(json.dumps({'type': 'assistant', 'timestamp': f'2026-09-22T01:0{n}:00Z',
                'message': {'id': f'm{n}', 'model': model, 'usage': {'input_tokens': total}}}))
        report = claude_report(lines, timezone='Asia/Shanghai', now=NOW)
        self.assert_conserved(report)
        expected = {'claude-opus': 120, 'claude-sonnet': 200, 'unknown': 50}
        self.assertEqual({m['model']: m['total_tokens'] for m in report['hourly'][0]['model_breakdowns']}, expected)
        config = DeviceConfig(1, 'model-test', 'host', 'host', 'user', 'darwin', 'Asia/Shanghai', 'https://example.test/ingest')
        facts = _usage_hourly_facts_from_mswusage(config, report, provider_key='claude', default_agent='claude')
        self.assertEqual(len(facts), 1)
        self.assertEqual({m['model']: m['total_tokens'] for m in facts[0]['model_breakdowns']}, expected)
        self.assertEqual(sum(expected.values()), facts[0]['usage']['total_tokens'])

    def test_model_field_cannot_export_paths_or_free_text(self):
        lines = [json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-sol'}}), codex_event(0, 100),
                 json.dumps({'type': 'turn_context', 'payload': {'model': '/Users/private/secret'}}), codex_event(1, 50)]
        report = codex_report(lines, timezone='Asia/Shanghai', now=NOW)
        self.assert_conserved(report)
        self.assertNotIn('/Users/private/secret', json.dumps(report))
        self.assertEqual({m['model']: m['total_tokens'] for m in report['hourly'][0]['model_breakdowns']},
                         {'gpt-6-sol': 100, 'unknown': 50})
