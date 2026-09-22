from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.limits import LimitContractError
from ai_usage_widget.codex_limits_provider import (
    CodexLimitsProvider,
    CodexProviderError,
    parse_codex_rpc_rate_limits,
    parse_codex_wham_usage,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingFetcher:
    def __init__(self, payload: dict | None = None, error: CodexProviderError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.payload is None:
            raise AssertionError("fetcher payload was not configured")
        return self.payload


class RecordingRpcReader:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        return self.payload


class TestCodexLimitsProvider(unittest.TestCase):
    def test_wham_names_each_window_by_its_duration_not_its_position(self) -> None:
        for field in ("primary_window", "secondary_window"):
            for minutes, expected in ((300, "session"), (10080, "week"), (1440, "day"), (120, "120m")):
                with self.subTest(field=field, minutes=minutes):
                    windows = parse_codex_wham_usage({
                        "observed_at": "2026-06-03T09:30:00+08:00",
                        "rate_limit": {
                            "primary_window": None,
                            "secondary_window": None,
                            field: {
                                "used_percent": 17,
                                "reset_at": "2026-06-08T00:00:00+08:00",
                                "limit_window_seconds": minutes * 60,
                            },
                        },
                    })
                    self.assertEqual(len(windows), 1)
                    self.assertEqual(windows[0].window, expected)
                    self.assertEqual(windows[0].window_duration_minutes, minutes)
                    self.assertEqual(windows[0].used_percent, 17)
                    self.assertTrue(windows[0].is_official)

    def test_rpc_names_each_window_by_its_duration_not_its_position(self) -> None:
        for field in ("primary", "secondary"):
            for minutes, expected in ((300, "session"), (10080, "week"), (1440, "day"), (120, "120m")):
                with self.subTest(field=field, minutes=minutes):
                    windows = parse_codex_rpc_rate_limits({
                        "result": {
                            "rateLimits": {
                                "primary": None,
                                "secondary": None,
                                field: {
                                    "usedPercent": 23,
                                    "resetsAt": "2026-06-08T00:00:00+08:00",
                                    "windowDurationMins": minutes,
                                },
                            },
                        },
                    }, observed_at="2026-06-03T09:30:00+08:00")
                    self.assertEqual(len(windows), 1)
                    self.assertEqual(windows[0].window, expected)
                    self.assertEqual(windows[0].window_duration_minutes, minutes)
                    self.assertEqual(windows[0].used_percent, 23)
                    self.assertTrue(windows[0].is_official)

    def test_rpc_selects_codex_main_bucket_over_legacy_or_other_models(self) -> None:
        legacy = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))
        main = {
            "primary": {
                "usedPercent": 7,
                "resetsAt": "2026-06-08T00:00:00+08:00",
                "windowDurationMins": 10080,
            },
            "secondary": None,
        }
        for include_legacy in (False, True):
            with self.subTest(include_legacy=include_legacy):
                payload = {
                    "observed_at": legacy["observed_at"],
                    "rateLimitsByLimitId": {"codex-spark": legacy["rate_limits"], "codex": main},
                }
                if include_legacy:
                    payload["rateLimits"] = legacy["rate_limits"]
                windows = parse_codex_rpc_rate_limits(payload)
                self.assertEqual(len(windows), 1)
                self.assertEqual(windows[0].window, "week")
                self.assertEqual(windows[0].window_duration_minutes, 10080)
                self.assertEqual(windows[0].used_percent, 7)
                self.assertEqual(windows[0].remaining_percent, 93)

    def test_rpc_missing_or_invalid_main_bucket_never_uses_other_model_or_legacy(self) -> None:
        legacy = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))
        for buckets in ({}, {"codex-spark": legacy["rate_limits"]}, {"codex": None}, {"codex": {}}):
            with self.subTest(buckets=buckets):
                with self.assertRaises(LimitContractError):
                    parse_codex_rpc_rate_limits({**legacy, "rateLimitsByLimitId": buckets})

    def test_rpc_null_bucket_map_retains_legacy_window_response(self) -> None:
        legacy = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))
        windows = parse_codex_rpc_rate_limits({**legacy, "rateLimitsByLimitId": None})
        self.assertEqual(len(windows), 2)
        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.used_percent for window in windows], [63, 44])

    def test_wham_fixture_maps_primary_and_secondary_windows(self) -> None:
        payload = json.loads((FIXTURES / "codex_wham_usage.json").read_text(encoding="utf-8"))

        windows = parse_codex_wham_usage(payload)

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.window_duration_minutes for window in windows], [300, 10080])
        self.assertEqual(windows[0].provider, "codex")
        self.assertEqual(windows[0].used_percent, 41.2)
        self.assertEqual(windows[0].remaining_percent, 58.8)
        self.assertEqual(windows[0].source_type, "runtime_api")
        self.assertEqual(windows[0].confidence, "observed")
        self.assertTrue(all(window.is_official for window in windows))

    def test_wham_current_response_maps_nested_rate_limit_windows(self) -> None:
        payload = {
            "observed_at": "2026-06-03T10:00:00+08:00",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25,
                    "reset_at": 1780480800,
                    "limit_window_seconds": 18000,
                },
                "secondary_window": {
                    "used_percent": 40,
                    "reset_at": 1780920000,
                    "limit_window_seconds": 604800,
                },
            },
        }

        windows = parse_codex_wham_usage(payload)

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.window_duration_minutes for window in windows], [300, 10080])
        self.assertEqual([window.used_percent for window in windows], [25.0, 40.0])
        self.assertTrue(all(window.is_official for window in windows))

    def test_wham_missing_primary_keeps_only_verified_secondary_window(self) -> None:
        windows = parse_codex_wham_usage({
            "observed_at": "2026-07-18T10:00:00+08:00",
            "rate_limit": {
                "secondary_window": {
                    "used_percent": 34,
                    "reset_at": 1784556000,
                    "limit_window_seconds": 604800,
                },
            },
        })

        self.assertEqual([window.window for window in windows], ["week"])
        self.assertEqual(windows[0].used_percent, 34)

    def test_wham_present_but_changed_window_schema_fails_closed(self) -> None:
        with self.assertRaisesRegex(Exception, "used_percent"):
            parse_codex_wham_usage({
                "observed_at": "2026-07-18T10:00:00+08:00",
                "rate_limit": {
                    "primary_window": {
                        "percentage": 34,
                        "reset_at": 1784556000,
                        "limit_window_seconds": 86400,
                    },
                },
            })

    def test_rpc_rate_limits_fixture_maps_fallback_windows(self) -> None:
        payload = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))

        windows = parse_codex_rpc_rate_limits(payload)

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].reset_at, "2026-06-03T14:30:00+08:00")
        self.assertEqual(windows[0].used_percent, 63.0)
        self.assertEqual(windows[0].remaining_percent, 37.0)
        self.assertEqual(windows[0].source_type, "cli_rpc")
        self.assertEqual(windows[0].confidence, "observed")
        self.assertTrue(all(window.is_official for window in windows))

    def test_auto_strategy_prefers_wham_over_rpc(self) -> None:
        wham_payload = json.loads((FIXTURES / "codex_wham_usage.json").read_text(encoding="utf-8"))
        rpc_payload = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))
        fetcher = RecordingFetcher(wham_payload)
        rpc_reader = RecordingRpcReader(rpc_payload)

        windows = CodexLimitsProvider(wham_fetcher=fetcher, rpc_reader=rpc_reader).collect()

        self.assertEqual([window.source_type for window in windows], ["runtime_api", "runtime_api"])
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(rpc_reader.calls, 0)

    def test_auto_strategy_falls_back_to_rpc_for_oauth_auth_errors(self) -> None:
        rpc_payload = json.loads((FIXTURES / "codex_rpc_rate_limits.json").read_text(encoding="utf-8"))

        for error_type in ["missing_credentials", "unauthorized"]:
            with self.subTest(error_type=error_type):
                fetcher = RecordingFetcher(error=CodexProviderError(error_type, "OAuth unavailable"))
                rpc_reader = RecordingRpcReader(rpc_payload)

                windows = CodexLimitsProvider(wham_fetcher=fetcher, rpc_reader=rpc_reader).collect()

                self.assertEqual([window.source_type for window in windows], ["cli_rpc", "cli_rpc"])
                self.assertEqual(fetcher.calls, 1)
                self.assertEqual(rpc_reader.calls, 1)


if __name__ == "__main__":
    unittest.main()
