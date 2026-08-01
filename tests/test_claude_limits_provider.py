from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.claude_limits_provider import (
    ClaudeLimitsProvider,
    ClaudeProviderError,
    parse_claude_cli_usage,
    parse_claude_active_limits,
    parse_claude_local_history_estimate,
    parse_claude_oauth_usage,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingOAuthFetcher:
    def __init__(self, payload: dict | None = None, error: ClaudeProviderError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.payload is None:
            raise AssertionError("OAuth payload was not configured")
        return self.payload


class RecordingCliReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.text


class TestClaudeLimitsProvider(unittest.TestCase):
    def test_oauth_fixture_outputs_session_and_weekly_windows(self) -> None:
        payload = json.loads((FIXTURES / "claude_oauth_usage.json").read_text(encoding="utf-8"))

        windows = parse_claude_oauth_usage(payload)

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.window_duration_minutes for window in windows], [300, 10080])
        self.assertEqual(windows[0].provider, "claude")
        self.assertEqual(windows[0].used_percent, 52.0)
        self.assertEqual(windows[0].source_type, "oauth_usage_api")
        self.assertEqual(windows[0].confidence, "observed")
        self.assertTrue(all(window.is_official for window in windows))

    def test_current_oauth_usage_shape_maps_five_hour_and_seven_day(self) -> None:
        windows = parse_claude_oauth_usage({
            "five_hour": {"utilization": 12.5, "resets_at": "2026-07-18T14:00:00+00:00"},
            "seven_day": {"utilization": 34.0, "resets_at": "2026-07-23T00:00:00+00:00"},
            "observed_at": "2026-07-18T12:00:00+00:00",
        })

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.used_percent for window in windows], [12.5, 34.0])
        self.assertEqual([window.window_duration_minutes for window in windows], [300, 10080])
        self.assertTrue(all(window.source_type == "oauth_usage_api" for window in windows))
        self.assertTrue(all(window.is_official for window in windows))

    def test_cli_usage_fixture_parses_used_percent_and_reset_time(self) -> None:
        text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")

        windows = parse_claude_cli_usage(text, observed_at="2026-06-03T10:01:00+08:00")

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].used_percent, 68.0)
        self.assertEqual(windows[0].remaining_percent, 32.0)
        self.assertEqual(windows[0].reset_at, "2026-06-03T15:30:00+08:00")
        self.assertEqual(windows[0].source_type, "official_cli")
        self.assertTrue(all(window.is_official for window in windows))

    def test_active_limits_cache_parses_rate_limit_windows(self) -> None:
        payload = {
            "rate_limits": {
                "five_hour": {"used_percentage": 10, "resets_at": 1780480800},
                "seven_day": {"used_percentage": 20, "resets_at": 1780920000},
            }
        }

        windows = parse_claude_active_limits(payload, observed_at="2026-06-03T10:01:00+08:00")

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.window_duration_minutes for window in windows], [300, 10080])
        self.assertEqual([window.used_percent for window in windows], [10.0, 20.0])
        self.assertEqual([window.source_type for window in windows], ["active_limits_cache", "active_limits_cache"])
        self.assertEqual([window.confidence for window in windows], ["estimated", "estimated"])
        self.assertEqual([window.status for window in windows], ["unavailable", "unavailable"])
        self.assertFalse(any(window.is_official for window in windows))

    def test_cli_limit_message_parses_session_window(self) -> None:
        windows = parse_claude_cli_usage(
            "You've hit your session limit · resets 11:40am (Asia/Shanghai)",
            observed_at="2026-06-03T11:20:00+08:00",
        )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].window, "session")
        self.assertEqual(windows[0].used_percent, 100.0)
        self.assertEqual(windows[0].remaining_percent, 0.0)
        self.assertEqual(windows[0].reset_at, "2026-06-03T11:40:00+08:00")
        self.assertEqual(windows[0].window_duration_minutes, 300)
        self.assertEqual(windows[0].source_type, "official_cli_limit_message")
        self.assertTrue(windows[0].is_official)

    def test_cli_new_format_parses_subscription_usage_text(self) -> None:
        text = (
            "You are currently using your subscription to power your Claude Code usage\n\n"
            "Current session: 35% used · resets Jun 19 at 6:09pm (Asia/Shanghai)\n"
            "Current week (all models): 40% used · resets Jun 21 at 1:59am (Asia/Shanghai)\n"
        )

        windows = parse_claude_cli_usage(text, observed_at="2026-06-19T14:00:00+08:00")

        self.assertEqual([w.window for w in windows], ["session", "week"])
        self.assertEqual([w.used_percent for w in windows], [35.0, 40.0])
        self.assertEqual([w.remaining_percent for w in windows], [65.0, 60.0])
        self.assertEqual(windows[0].reset_at, "2026-06-19T18:09:00+08:00")
        self.assertEqual(windows[1].reset_at, "2026-06-21T01:59:00+08:00")
        self.assertEqual([w.window_duration_minutes for w in windows], [300, 10080])
        self.assertEqual([w.source_type for w in windows], ["official_cli", "official_cli"])
        self.assertTrue(all(w.is_official for w in windows))

    def test_cli_new_format_accepts_reset_without_minutes(self) -> None:
        text = (
            "You are currently using your subscription to power your Claude Code usage\n\n"
            "Current session: 17% used · resets Jun 24 at 7:40pm (Asia/Shanghai)\n"
            "Current week (all models): 51% used · resets Jun 28 at 2am (Asia/Shanghai)\n"
        )

        windows = parse_claude_cli_usage(text, observed_at="2026-06-24T15:17:00+08:00")

        self.assertEqual([w.window for w in windows], ["session", "week"])
        self.assertEqual([w.used_percent for w in windows], [17.0, 51.0])
        self.assertEqual(windows[0].reset_at, "2026-06-24T19:40:00+08:00")
        self.assertEqual(windows[1].reset_at, "2026-06-28T02:00:00+08:00")
        self.assertEqual([w.source_type for w in windows], ["official_cli", "official_cli"])

    def test_cli_limit_message_next_day_when_reset_time_already_passed(self) -> None:
        windows = parse_claude_cli_usage(
            "You've hit your session limit · resets 12:10am (Asia/Shanghai)",
            observed_at="2026-06-03T23:50:00+08:00",
        )

        self.assertEqual(windows[0].reset_at, "2026-06-04T00:10:00+08:00")

    def test_oauth_success_does_not_trigger_cli_fallback(self) -> None:
        oauth_payload = json.loads((FIXTURES / "claude_oauth_usage.json").read_text(encoding="utf-8"))
        fetcher = RecordingOAuthFetcher(oauth_payload)
        cli_reader = RecordingCliReader((FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8"))

        windows = ClaudeLimitsProvider(oauth_fetcher=fetcher, cli_usage_reader=cli_reader).collect()

        self.assertEqual([window.source_type for window in windows], ["oauth_usage_api", "oauth_usage_api"])
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(cli_reader.calls, 0)

    def test_oauth_auth_errors_fall_back_to_cli_usage(self) -> None:
        cli_text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")

        for error_type in ["missing_credentials", "unauthorized"]:
            with self.subTest(error_type=error_type):
                fetcher = RecordingOAuthFetcher(error=ClaudeProviderError(error_type, "OAuth unavailable"))
                cli_reader = RecordingCliReader(cli_text)

                windows = ClaudeLimitsProvider(
                    oauth_fetcher=fetcher,
                    cli_usage_reader=cli_reader,
                    observed_at_provider=lambda: "2026-06-03T10:01:00+08:00",
                ).collect()

                self.assertEqual([window.source_type for window in windows], ["official_cli", "official_cli"])
                self.assertEqual(fetcher.calls, 1)
                self.assertEqual(cli_reader.calls, 1)

    def test_local_project_history_cannot_output_official_reset(self) -> None:
        window = parse_claude_local_history_estimate(
            {
                "window": "session",
                "used_percent": 70,
                "reset_at": "2026-06-03T15:00:00+08:00",
                "observed_at": "2026-06-03T10:02:00+08:00",
            }
        )

        self.assertEqual(window.source_type, "local_history_estimate")
        self.assertEqual(window.confidence, "estimated")
        self.assertFalse(window.is_official)


if __name__ == "__main__":
    unittest.main()
