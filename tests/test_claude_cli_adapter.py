from __future__ import annotations

import unittest
from pathlib import Path

from ai_usage_widget.claude_limits_provider import (
    ClaudeCliUsageProvider,
    ClaudeCommandResult,
    ClaudeOAuthWithCliFallbackProvider,
    ClaudeProviderError,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingRunner:
    def __init__(self, result: ClaudeCommandResult | list[ClaudeCommandResult]) -> None:
        self.results = list(result) if isinstance(result, list) else [result]
        self.calls: list[dict] = []

    def run(self, command: list[str], timeout: float, env: dict[str, str] | None = None) -> ClaudeCommandResult:
        self.calls.append({"command": command, "timeout": timeout, "env": env})
        return self.results.pop(0)


class BrokenOAuthProvider:
    def __init__(self, error_type: str) -> None:
        self.error_type = error_type

    def collect(self):
        raise ClaudeProviderError(self.error_type, "OAuth unavailable")


class TestClaudeCliAdapter(unittest.TestCase):
    def test_cli_provider_runs_usage_command_and_parses_windows(self) -> None:
        cli_text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")
        runner = RecordingRunner(ClaudeCommandResult(returncode=0, stdout=cli_text, stderr=""))

        windows = ClaudeCliUsageProvider(
            runner=runner,
            timeout=8.0,
            observed_at_provider=lambda: "2026-06-03T10:01:00+08:00",
        ).collect()

        self.assertEqual(runner.calls[0]["command"], ["claude", "-p", "/usage", "--output-format", "text", "--no-session-persistence"])
        self.assertEqual(runner.calls[0]["timeout"], 8.0)
        self.assertIsNone(runner.calls[0]["env"])
        self.assertEqual([window.window for window in windows], ["session", "week"])
        self.assertEqual([window.source_type for window in windows], ["official_cli", "official_cli"])
        self.assertTrue(all(window.is_official for window in windows))

    def test_cli_provider_passes_configured_env(self) -> None:
        cli_text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")
        runner = RecordingRunner(ClaudeCommandResult(returncode=0, stdout=cli_text, stderr=""))

        ClaudeCliUsageProvider(
            runner=runner,
            env={"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"},
            observed_at_provider=lambda: "2026-06-03T10:01:00+08:00",
        ).collect()

        self.assertEqual(runner.calls[0]["env"], {"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"})

    def test_cli_provider_probes_limit_message_when_usage_unavailable(self) -> None:
        runner = RecordingRunner(
            [
                ClaudeCommandResult(
                    returncode=0,
                    stdout="You are currently using your subscription to power your Claude Code usage",
                    stderr="",
                ),
                ClaudeCommandResult(
                    returncode=1,
                    stdout="You've hit your session limit · resets 11:40am (Asia/Shanghai)",
                    stderr="",
                ),
            ]
        )

        windows = ClaudeCliUsageProvider(
            runner=runner,
            env={"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"},
            observed_at_provider=lambda: "2026-06-03T11:20:00+08:00",
        ).collect()

        self.assertEqual([call["command"] for call in runner.calls], [
            ["claude", "-p", "/usage", "--output-format", "text", "--no-session-persistence"],
            ["claude", "-p", "Respond with OK only.", "--output-format", "text", "--no-session-persistence"],
        ])
        self.assertEqual(runner.calls[1]["env"], {"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"})
        self.assertEqual([(window.window, window.used_percent, window.source_type) for window in windows], [
            ("session", 100.0, "official_cli_limit_message")
        ])

    def test_cli_provider_maps_nonzero_exit_to_provider_failed(self) -> None:
        runner = RecordingRunner(ClaudeCommandResult(returncode=1, stdout="", stderr="login required"))

        with self.assertRaises(ClaudeProviderError) as caught:
            ClaudeCliUsageProvider(runner=runner).collect()

        self.assertEqual(caught.exception.error_type, "provider_failed")

    def test_oauth_auth_failure_falls_back_to_cli_provider(self) -> None:
        cli_text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")
        runner = RecordingRunner(ClaudeCommandResult(returncode=0, stdout=cli_text, stderr=""))

        windows = ClaudeOAuthWithCliFallbackProvider(
            oauth_provider=BrokenOAuthProvider("unauthorized"),
            cli_provider=ClaudeCliUsageProvider(
                runner=runner,
                observed_at_provider=lambda: "2026-06-03T10:01:00+08:00",
            ),
        ).collect()

        self.assertEqual([window.source_type for window in windows], ["official_cli", "official_cli"])
        self.assertEqual(len(runner.calls), 1)

    def test_oauth_provider_failed_does_not_fallback_to_cli_provider(self) -> None:
        cli_text = (FIXTURES / "claude_usage_cli.txt").read_text(encoding="utf-8")
        runner = RecordingRunner(ClaudeCommandResult(returncode=0, stdout=cli_text, stderr=""))

        with self.assertRaises(ClaudeProviderError) as caught:
            ClaudeOAuthWithCliFallbackProvider(
                oauth_provider=BrokenOAuthProvider("provider_failed"),
                cli_provider=ClaudeCliUsageProvider(runner=runner),
            ).collect()

        self.assertEqual(caught.exception.error_type, "provider_failed")
        self.assertEqual(len(runner.calls), 0)


if __name__ == "__main__":
    unittest.main()
