from __future__ import annotations

import json
import unittest

from ai_usage_widget.codex_limits_provider import (
    CodexAppServerRPCProvider,
    CodexCommandResult,
    CodexProviderError,
    parse_codex_rpc_rate_limits,
)


class RecordingRunner:
    def __init__(self, result: CodexCommandResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def run(self, command: list[str], stdin: str, timeout: float) -> CodexCommandResult:
        self.calls.append({"command": command, "stdin": stdin, "timeout": timeout})
        return self.result


class TestCodexAppServerRPCAdapter(unittest.TestCase):
    def test_app_server_schema_response_maps_to_limit_windows(self) -> None:
        payload = {
            "rateLimits": {
                "primary": {
                    "usedPercent": 63,
                    "resetsAt": 1780480800,
                    "windowDurationMins": 300,
                },
                "secondary": {
                    "usedPercent": 44,
                    "resetsAt": 1780920000,
                    "windowDurationMins": 10080,
                },
            }
        }

        windows = parse_codex_rpc_rate_limits(payload, observed_at="2026-06-03T09:31:00+08:00")

        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual(windows[0].reset_at, "2026-06-03T10:00:00+00:00")
        self.assertEqual(windows[0].used_percent, 63.0)
        self.assertEqual(windows[0].remaining_percent, 37.0)
        self.assertEqual(windows[0].source_type, "cli_rpc")
        self.assertTrue(all(window.is_official for window in windows))

    def test_rpc_provider_sends_rate_limits_read_request_to_proxy(self) -> None:
        response = {
            "id": "ai-usage-widget-rate-limits",
            "result": {
                "rateLimits": {
                    "primary": {"usedPercent": 12, "resetsAt": 1780480800, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 25, "resetsAt": 1780920000, "windowDurationMins": 10080},
                }
            },
        }
        runner = RecordingRunner(CodexCommandResult(returncode=0, stdout=json.dumps(response), stderr=""))

        windows = CodexAppServerRPCProvider(
            runner=runner,
            socket_path="/tmp/codex-app-server.sock",
            timeout=9.0,
            observed_at_provider=lambda: "2026-06-03T09:31:00+08:00",
        ).collect()

        request = json.loads(runner.calls[0]["stdin"])
        self.assertEqual(runner.calls[0]["command"], ["codex", "app-server", "proxy", "--sock", "/tmp/codex-app-server.sock"])
        self.assertEqual(runner.calls[0]["timeout"], 9.0)
        self.assertEqual(request["method"], "account/rateLimits/read")
        self.assertIsNone(request["params"])
        self.assertEqual([window.source_type for window in windows], ["cli_rpc", "cli_rpc"])

    def test_rpc_missing_primary_keeps_only_verified_secondary_window(self) -> None:
        windows = parse_codex_rpc_rate_limits(
            {
                "rateLimits": {
                    "secondary": {
                        "usedPercent": 25,
                        "resetsAt": 1784556000,
                        "windowDurationMins": 10080,
                    },
                }
            },
            observed_at="2026-07-18T10:00:00+08:00",
        )

        self.assertEqual([window.window for window in windows], ["week"])

    def test_rpc_provider_maps_nonzero_exit_to_provider_failed(self) -> None:
        runner = RecordingRunner(CodexCommandResult(returncode=1, stdout="", stderr="socket unavailable"))

        with self.assertRaises(CodexProviderError) as caught:
            CodexAppServerRPCProvider(runner=runner).collect()

        self.assertEqual(caught.exception.error_type, "provider_failed")


if __name__ == "__main__":
    unittest.main()
