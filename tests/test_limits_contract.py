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

    def test_observed_success_requires_both_measured_percentages(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        for missing in [("used_percent",), ("remaining_percent",), ("used_percent", "remaining_percent")]:
            with self.subTest(missing=missing):
                incomplete = dict(payload)
                for field in missing:
                    incomplete.pop(field)
                with self.assertRaises(LimitContractError) as caught:
                    parse_limit_window(incomplete)
                self.assertEqual(caught.exception.error_type, "limit_schema_invalid")

    def test_measurements_reject_non_finite_values_and_preserve_true_zero(self) -> None:
        payload = json.loads((FIXTURES / "limits_official_sample.json").read_text(encoding="utf-8"))
        for field in ["used_percent", "remaining_percent"]:
            for value in [None, float("nan"), float("inf"), float("-inf")]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(LimitContractError):
                        parse_limit_window({**payload, field: value})
        for used, remaining in [(0, 100), (100, 0), (0, 0)]:
            window = parse_limit_window({**payload, "used_percent": used, "remaining_percent": remaining})
            self.assertTrue(window.is_official)
            self.assertEqual((window.used_percent, window.remaining_percent), (used, remaining))
        failed = parse_limit_window({**payload, "status": "provider_failed", "confidence": "missing",
            "reset_at": payload["observed_at"], "window_duration_minutes": 0, "used_percent": 0, "remaining_percent": 0})
        self.assertFalse(failed.is_official)

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
