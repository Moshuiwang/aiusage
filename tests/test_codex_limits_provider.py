from __future__ import annotations

import json
import unittest
from pathlib import Path

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
