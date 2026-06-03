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
                                "remainingFraction": 0.72,
                                "windowDurationMins": 300,
                            }
                        }
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
