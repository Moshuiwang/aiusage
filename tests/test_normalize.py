import unittest
from pathlib import Path

from ai_usage_widget.normalize import normalize_ccusage_daily


SOURCE = {
    "source_id": "mac-local",
    "host_label": "macbook",
    "os_user": "local",
}


class NormalizeTest(unittest.TestCase):
    def test_normalize_ccusage_daily_fixture(self):
        payload = Path("tests/fixtures/ccusage_daily_sample.json").read_text(encoding="utf-8")

        result = normalize_ccusage_daily(SOURCE, payload)

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.items), 2)
        first = result.items[0]
        self.assertEqual(first.machine, "macbook")
        self.assertEqual(first.account, "local")
        self.assertEqual(first.agent, "codex")
        self.assertEqual(first.date, "2026-05-22")
        self.assertEqual(first.total_tokens, 1800)
        self.assertEqual(first.model_breakdowns[0]["model_name"], "gpt-5")

    def test_normalize_uses_unknown_agent_and_computed_total(self):
        payload = Path("tests/fixtures/ccusage_daily_sample.json").read_text(encoding="utf-8")

        result = normalize_ccusage_daily(SOURCE, payload)

        second = result.items[1]
        self.assertEqual(second.agent, "unknown")
        self.assertEqual(second.total_tokens, 30)

    def test_normalize_rejects_unsupported_shape(self):
        result = normalize_ccusage_daily(SOURCE, '{"totals": {}}')

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "unsupported_shape")


if __name__ == "__main__":
    unittest.main()
