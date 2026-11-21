from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget import cli
from ai_usage_widget.cli import _providers_from_limits_config
from ai_usage_widget.limits import LimitContractError
from ai_usage_widget.limits_config import parse_limits_config


def _native_result() -> dict:
    now = datetime.now(timezone.utc)
    weekly_reset = (now + timedelta(days=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    short_reset = (now + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "status": "SUCCESS",
        "num_turns": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
        },
        "response": "\n".join(
            (
                f"Gemini Models\tWeekly Limit Remaining\t95%\t{weekly_reset}",
                f"Gemini Models\tFive Hour Limit Remaining\t96%\t{short_reset}",
                f"Claude and GPT models\tWeekly Limit Remaining\t100%\t{weekly_reset}",
                f"Claude and GPT models\tFive Hour Limit Remaining\t100%\t{short_reset}",
                f"Gemini 4 Argon\tGemini 4 Argon Weekly Limit\t99%\t{weekly_reset}",
            )
        ),
    }


class TestAntigravityCliLimitsProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.desktop = patch(
            "ai_usage_widget.antigravity_limits_provider.AntigravityLimitsProvider.collect",
            side_effect=AssertionError("CLI selection ran the desktop provider"),
        )
        self.desktop.start()
        self.addCleanup(self.desktop.stop)
        config = parse_limits_config(
            {
                "timezone": "Asia/Shanghai",
                "providers": [{"provider": "antigravity", "source_id": "tz-agy", "cli": True}],
            }
        )
        self.provider = _providers_from_limits_config(config.enabled_providers)["tz-agy"]

    @patch("subprocess.run")
    def test_explicit_cli_collects_native_quota_as_official_windows(self, run) -> None:
        result = _native_result()
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
        windows = self.provider.collect()
        self.assertEqual(
            [(window.window, window.window_duration_minutes, window.remaining_percent) for window in windows],
            [
                ("session", 300, 96.0),
                ("week", 10080, 95.0),
                ("claude_gpt_session", 300, 100.0),
                ("claude_gpt_week", 10080, 100.0),
                ("argon_week", 10080, 99.0),
            ],
        )
        self.assertEqual(windows[0].reset_at, result["response"].splitlines()[1].split("\t")[3])
        self.assertTrue(all(window.is_official and window.source_type == "official_cli" for window in windows))
        self.assertEqual(windows[0].used_percent, 4.0)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[0], "agy")
        self.assertEqual(command[command.index("-p") + 1], "/usage")
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        self.assertFalse(json.loads(command[command.index("--settings") + 1])["disableSlashCommands"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    @patch("subprocess.run")
    def test_missing_optional_pools_leaves_the_verified_primary_pair(self, run) -> None:
        result = _native_result()
        result["response"] = "\n".join(result["response"].splitlines()[:2])
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
        self.assertEqual([window.window for window in self.provider.collect()], ["session", "week"])

    @patch("subprocess.run")
    def test_push_limits_sends_one_batch_without_exposing_ingest_credentials_to_agy(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(_native_result()), stderr="")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "limits.json"
            config.write_text(json.dumps({
                "timezone": "Asia/Shanghai",
                "providers": [{"provider": "antigravity", "source_id": "tz-agy", "cli": True}],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"AI_USAGE_SAMPLE_INGEST_TOKEN": "sample-ingest-secret"}), \
                    patch.object(cli, "push_limits_payload", return_value={"success": True, "windows_written": 5}) as push, \
                    redirect_stdout(io.StringIO()):
                status = cli.main([
                    "push-limits", "--limits-config", str(config), "--token-env", "AI_USAGE_SAMPLE_INGEST_TOKEN",
                    "--url", "https://example.invalid/ingest-limits",
                ])

        self.assertEqual(status, 0)
        push.assert_called_once()
        windows = push.call_args.args[2]["windows"]
        self.assertEqual(len(windows), 5)
        self.assertEqual({window["source_id"] for window in windows}, {"tz-agy"})
        self.assertTrue(all(window["official"] for window in windows))
        self.assertNotIn("sample-ingest-secret", json.dumps(windows))
        self.assertIsNotNone(run.call_args.kwargs["env"])
        self.assertNotIn("AI_USAGE_SAMPLE_INGEST_TOKEN", run.call_args.kwargs["env"])

    @patch("subprocess.run")
    def test_rejects_model_calls_and_unverified_cli_envelopes(self, run) -> None:
        attempted_model_call = _native_result()
        attempted_model_call["usage"]["output_tokens"] = 1
        completed_turn = _native_result()
        completed_turn["num_turns"] = 1
        missing_usage = _native_result()
        del missing_usage["usage"]["input_tokens"]
        for result in (
            attempted_model_call,
            completed_turn,
            missing_usage,
            dict(_native_result(), status="ERROR", error="sample-auth-diagnostic"),
        ):
            with self.subTest(status=result["status"], turns=result["num_turns"]):
                run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
                with self.assertRaisesRegex(LimitContractError, r"Antigravity CLI") as error:
                    self.provider.collect()
                self.assertNotIn("sample-auth-diagnostic", str(error.exception))

    @patch("subprocess.run")
    def test_rejects_incomplete_ambiguous_or_malformed_windows(self, run) -> None:
        result = _native_result()
        first, second, third, fourth, fifth = result["response"].splitlines()
        for response in (
            "\n".join((first, third, fourth, fifth)),
            "\n".join((first, second, third, fifth)),
            "\n".join((first, second, first)),
            "\n".join((first[:-1], second)),
            "\n".join((first[:-1] + "+0000", second)),
            "\n".join((first, second.replace("96%", "196%"))),
            "\n".join((first, second.replace("Remaining", "Used"))),
            "\n".join((first, second, "generated text without quota fields")),
        ):
            with self.subTest(response=response):
                run.return_value = subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(dict(result, response=response)), stderr=""
                )
                with self.assertRaises(LimitContractError):
                    self.provider.collect()

    @patch("subprocess.run")
    def test_sanitizes_command_failures_and_timeouts(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="sample-auth-diagnostic")
        with self.assertRaisesRegex(RuntimeError, r"Antigravity CLI") as error:
            self.provider.collect()
        self.assertEqual(error.exception.error_type, "provider_unavailable")
        self.assertNotIn("sample-auth-diagnostic", str(error.exception))
        run.side_effect = subprocess.TimeoutExpired(["agy"], 45.0, output="sample-raw-output")
        with self.assertRaisesRegex(RuntimeError, r"Antigravity CLI") as error:
            self.provider.collect()
        self.assertEqual(error.exception.error_type, "timeout")
        self.assertNotIn("sample-raw-output", str(error.exception))
