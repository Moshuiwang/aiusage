from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.limits import LimitContractError, parse_limit_window


FIXTURES = Path(__file__).parent / "fixtures"


class TestLimitsContract(unittest.TestCase):
    def test_official_limits_fixture_parses(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))

        window = parse_limit_window(payload)

        self.assertEqual(window.provider, "codex")
        self.assertEqual(window.window, "weekly")
        self.assertEqual(window.used_percent, 37.5)
        self.assertEqual(window.remaining_percent, 62.5)
        self.assertEqual(window.window_duration_minutes, 10080)
        self.assertEqual(window.source_type, "runtime_api")
        self.assertEqual(window.confidence, "observed")
        self.assertTrue(window.is_official)
        self.assertEqual(window.to_snapshot_dict()["reset_at"], "2026-06-08T00:00:00+08:00")

    def test_missing_required_fields_raise_stable_error(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))

        for field in ["provider", "window", "reset_at", "observed_at"]:
            malformed = dict(payload)
            malformed.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(LimitContractError) as ctx:
                    parse_limit_window(malformed)
                self.assertEqual(ctx.exception.error_type, "limit_schema_invalid")
                self.assertIn(field, str(ctx.exception))

    def test_non_observed_confidence_is_not_official(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        payload["confidence"] = "estimated"

        window = parse_limit_window(payload)

        self.assertFalse(window.is_official)
        self.assertEqual(window.to_snapshot_dict()["official"], False)

    def test_local_history_estimate_cannot_be_official_reset(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        payload["source_type"] = "local_history_estimate"

        window = parse_limit_window(payload)

        self.assertFalse(window.is_official)
        self.assertEqual(window.to_snapshot_dict()["official"], False)

    def test_cached_limit_cannot_claim_observed_ok(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        payload["source_type"] = "active_limits_cache"

        with self.assertRaises(LimitContractError) as caught:
            parse_limit_window(payload)

        self.assertEqual(caught.exception.error_type, "limit_schema_invalid")

    def test_expired_limit_cannot_claim_ok(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        payload["observed_at"] = "2026-06-09T00:00:00+08:00"

        with self.assertRaises(LimitContractError) as caught:
            parse_limit_window(payload)

        self.assertEqual(caught.exception.error_type, "limit_schema_invalid")


if __name__ == "__main__":
    unittest.main()
