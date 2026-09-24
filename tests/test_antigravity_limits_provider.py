from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.antigravity_limits_provider import (
    AntigravityLimitsProvider,
    AntigravityProviderError,
    parse_antigravity_command_model_configs,
    parse_antigravity_user_status,
)
from ai_usage_widget.limits import LimitContractError


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingReader:
    def __init__(self, payload: dict | None = None, error: AntigravityProviderError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.payload is None:
            raise AssertionError("reader payload was not configured")
        return self.payload


class TestAntigravityLimitsProvider(unittest.TestCase):
    def test_user_status_fixture_maps_language_server_windows(self) -> None:
        payload = json.loads((FIXTURES / "antigravity_user_status.json").read_text(encoding="utf-8"))

        windows = parse_antigravity_user_status(payload)

        self.assertEqual([window.window for window in windows], ["session", "day"])
        self.assertEqual(windows[0].provider, "antigravity")
        self.assertEqual(windows[0].used_percent, 28.0)
        self.assertEqual(windows[0].remaining_percent, 72.0)
        self.assertEqual(windows[0].reset_at, "2026-06-03T15:20:00+08:00")
        self.assertEqual(windows[0].source_type, "language_server")
        self.assertEqual(windows[0].confidence, "observed")
        self.assertTrue(all(window.is_official for window in windows))

    def test_command_model_configs_fixture_maps_fallback_windows(self) -> None:
        payload = json.loads((FIXTURES / "antigravity_command_model_configs.json").read_text(encoding="utf-8"))

        windows = parse_antigravity_command_model_configs(payload)

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].used_percent, 49.0)
        self.assertEqual(windows[0].remaining_percent, 51.0)
        self.assertEqual(windows[0].source_type, "language_server_config")
        self.assertEqual(windows[1].used_percent, 16.0)
        self.assertTrue(all(window.is_official for window in windows))

    def test_provider_prefers_user_status_over_command_model_configs(self) -> None:
        status_payload = json.loads((FIXTURES / "antigravity_user_status.json").read_text(encoding="utf-8"))
        config_payload = json.loads((FIXTURES / "antigravity_command_model_configs.json").read_text(encoding="utf-8"))
        status_reader = RecordingReader(status_payload)
        config_reader = RecordingReader(config_payload)

        windows = AntigravityLimitsProvider(
            user_status_reader=status_reader,
            command_model_configs_reader=config_reader,
        ).collect()

        self.assertEqual([window.source_type for window in windows], ["language_server", "language_server"])
        self.assertEqual(status_reader.calls, 1)
        self.assertEqual(config_reader.calls, 0)

    def test_provider_falls_back_to_command_model_configs_for_unavailable_status(self) -> None:
        config_payload = json.loads((FIXTURES / "antigravity_command_model_configs.json").read_text(encoding="utf-8"))
        status_reader = RecordingReader(error=AntigravityProviderError("unsupported", "GetUserStatus unavailable"))
        config_reader = RecordingReader(config_payload)

        windows = AntigravityLimitsProvider(
            user_status_reader=status_reader,
            command_model_configs_reader=config_reader,
        ).collect()

        self.assertEqual([window.source_type for window in windows], ["language_server_config", "language_server_config"])
        self.assertEqual(status_reader.calls, 1)
        self.assertEqual(config_reader.calls, 1)

    def test_missing_reset_time_is_rejected(self) -> None:
        with self.assertRaises(LimitContractError):
            parse_antigravity_user_status(
                {
                    "observed_at": "2026-06-03T10:20:00+08:00",
                    "user_status": {
                        "limits": {
                            "session": {
                            }
                        }
                    },
                }
            )

    def test_cascade_model_config_data_real_world_payload(self) -> None:
        payload = {
            "observed_at": "2026-09-24T08:20:00+08:00",
            "userStatus": {
                "userTier": {"id": "g1-pro-tier", "name": "Google AI Pro"},
                "cascadeModelConfigData": {
                    "clientModelConfigs": [
                        {
                            "label": "Gemini 3.8 Flash (High)",
                            "modelId": "gemini-3.8-flash-high",
                            "quotaInfo": {
                                "remainingFraction": 0.66,
                                "resetTime": "2026-09-24T04:40:21Z",
                            },
                        },
                        {
                            "label": "Claude Opus 4.6 (Thinking)",
                            "modelId": "claude-opus-4-6-thinking",
                            "quotaInfo": {
                                "remainingFraction": 1.0,
                                "resetTime": "2026-09-24T05:21:30Z",
                            },
                        },
                    ]
                },
            },
        }
        windows = parse_antigravity_user_status(payload)
        self.assertGreaterEqual(len(windows), 1)
        w0 = windows[0]
        self.assertEqual(w0.provider, "antigravity")
        self.assertEqual(w0.window, "session")
        self.assertAlmostEqual(w0.remaining_percent, 66.0)
        self.assertAlmostEqual(w0.used_percent, 34.0)
        self.assertEqual(w0.reset_at, "2026-09-24T04:40:21Z")
        self.assertEqual(w0.confidence, "observed")
        self.assertEqual(w0.status, "ok")

    def test_quota_summary_fixture_maps_both_session_and_week_windows(self) -> None:
        payload = json.loads((FIXTURES / "antigravity_quota_summary.json").read_text(encoding="utf-8"))

        windows = parse_antigravity_user_status(payload)

        self.assertEqual(len(windows), 2)
        session_w = windows[0]
        self.assertEqual(session_w.provider, "antigravity")
        self.assertEqual(session_w.window, "session")
        self.assertAlmostEqual(session_w.remaining_percent, 7.71614)
        self.assertAlmostEqual(session_w.used_percent, 92.28386)
        self.assertEqual(session_w.reset_at, "2026-09-24T04:40:21Z")
        self.assertEqual(session_w.window_duration_minutes, 300)
        self.assertEqual(session_w.source_type, "language_server")
        self.assertEqual(session_w.confidence, "observed")
        self.assertEqual(session_w.status, "ok")
        self.assertTrue(session_w.is_official)

        week_w = windows[1]
        self.assertEqual(week_w.provider, "antigravity")
        self.assertEqual(week_w.window, "week")
        self.assertAlmostEqual(week_w.remaining_percent, 78.984827)
        self.assertAlmostEqual(week_w.used_percent, 21.015173)
        self.assertEqual(week_w.reset_at, "2026-09-30T06:33:58Z")
        self.assertEqual(week_w.window_duration_minutes, 10080)
        self.assertEqual(week_w.source_type, "language_server")
        self.assertEqual(week_w.confidence, "observed")
        self.assertEqual(week_w.status, "ok")
        self.assertTrue(week_w.is_official)

    def test_quota_summary_handles_direct_groups_and_percent_fields(self) -> None:
        payload = {
            "observed_at": "2026-09-24T10:00:00+08:00",
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "window": "5h",
                            "remainingPercent": 16.0,
                            "resetTime": "2026-09-24T12:00:00Z",
                        },
                        {
                            "window": "weekly",
                            "remainingPercent": 80.0,
                            "resetTime": "2026-09-30T12:00:00Z",
                        },
                    ],
                }
            ],
        }
        windows = parse_antigravity_user_status(payload)
        self.assertEqual(len(windows), 2)
        self.assertEqual([w.window for w in windows], ["session", "week"])
        self.assertEqual(windows[0].remaining_percent, 16.0)
        self.assertEqual(windows[0].used_percent, 84.0)
        self.assertEqual(windows[0].reset_at, "2026-09-24T12:00:00Z")
        self.assertEqual(windows[1].remaining_percent, 80.0)
        self.assertEqual(windows[1].used_percent, 20.0)
        self.assertEqual(windows[1].reset_at, "2026-09-30T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
