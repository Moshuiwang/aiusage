from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_usage_widget.claude_limits_provider import (
    ClaudeLimitsProvider,
    ClaudeProviderError,
    parse_claude_cli_usage,
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

    def test_cli_usage_fixture_parses_used_percent_and_reset_time(self) -> None:
        text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")

        windows = parse_claude_cli_usage(text, observed_at="2026-06-03T10:01:00+08:00")

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].used_percent, 68.0)
        self.assertEqual(windows[0].remaining_percent, 32.0)
        self.assertEqual(windows[0].reset_at, "2026-06-03T15:30:00+08:00")
        self.assertEqual(windows[0].source_type, "official_cli")
        self.assertTrue(all(window.is_official for window in windows))

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

                windows = ClaudeLimitsProvider(oauth_fetcher=fetcher, cli_usage_reader=cli_reader).collect()

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
