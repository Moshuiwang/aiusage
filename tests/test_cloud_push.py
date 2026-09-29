from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_usage_widget import cli, cloud_push
from ai_usage_widget.account_fingerprint import compute_account_fingerprint
from ai_usage_widget.config import validate_device_config
from ai_usage_widget.pusher import _account_observations

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
ENV = {
    "AI_USAGE_INGEST_TOKEN": "test-token-not-real",
    "AI_USAGE_INGEST_URL": "https://example.invalid/ingest",
}


class FakePusher:
    """记录被构造时的配置与回看窗口；不做任何网络或磁盘采集。"""

    instances: list["FakePusher"] = []
    result: dict = {"success": True, "status": "accepted"}

    def __init__(self, config, **kwargs) -> None:
        self.config = config
        self.kwargs = kwargs
        self.pushed = False
        FakePusher.instances.append(self)

    def push(self) -> dict:
        self.pushed = True
        return dict(FakePusher.result)


class CloudPushCase(unittest.TestCase):
    def setUp(self) -> None:
        FakePusher.instances = []
        FakePusher.result = {"success": True, "status": "accepted"}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state.json"

    def run_hook(self, stdin='{"session_id": "abc-123"}', env=None, now=NOW, interval=None, final=False):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cloud_push.run(
                stdin_text=stdin,
                env=dict(ENV if env is None else env),
                state_path=self.state,
                now=now,
                pusher_factory=FakePusher,
                interval_minutes=interval,
                final=final,
            )
        return code, out.getvalue() + err.getvalue()


class TestSourceIdAndConfig(CloudPushCase):
    def test_source_id_derives_from_session_id(self) -> None:
        self.assertEqual(cloud_push.derive_source_id("abc-123"), "claude-cloud-abc-123")
        self.assertNotEqual(cloud_push.derive_source_id("a"), cloud_push.derive_source_id("b"))

    def test_source_id_strips_unsafe_characters(self) -> None:
        derived = cloud_push.derive_source_id("../.claude/x y")
        self.assertRegex(derived, r"^claude-cloud-[A-Za-z0-9_-]+$")
        self.assertNotIn(".claude", derived)

    def test_session_id_falls_back_to_stdin_then_cli_env(self) -> None:
        # 没有远程会话变量：stdin 兜底（覆盖 stdin 路径）
        self.assertEqual(cloud_push.resolve_session_id('{"session_id": "from-stdin"}', {}), "from-stdin")
        self.assertEqual(
            cloud_push.resolve_session_id("", {"CLAUDE_CODE_REMOTE_SESSION_ID": "env-1", "CLAUDE_CODE_SESSION_ID": "env-2"}),
            "env-1",
        )
        self.assertEqual(cloud_push.resolve_session_id("not json", {"CLAUDE_CODE_SESSION_ID": "env-2"}), "env-2")
        self.assertIsNone(cloud_push.resolve_session_id("", {}))

    def test_remote_session_env_wins_over_stdin_session_id(self) -> None:
        remote = {"CLAUDE_CODE_REMOTE_SESSION_ID": "cse_remote-1"}
        self.assertEqual(
            cloud_push.resolve_session_id('{"session_id": "cli-uuid"}', {**remote, "CLAUDE_CODE_SESSION_ID": "env-2"}),
            "cse_remote-1",
        )
        # 没有远程会话变量时 stdin 仍是兜底，且优先于 CLAUDE_CODE_SESSION_ID
        self.assertEqual(
            cloud_push.resolve_session_id('{"session_id": "cli-uuid"}', {"CLAUDE_CODE_SESSION_ID": "env-2"}),
            "cli-uuid",
        )

    def test_hook_and_manual_runs_share_one_source_id_in_same_container(self) -> None:
        """线上 bug 形态：Stop hook（有 stdin）与手动 cloud-push（无 stdin）同容器必须同一 source_id。"""
        env = {**ENV, "CLAUDE_CODE_REMOTE_SESSION_ID": "cse_013Qbc-test", "AI_USAGE_CLOUD_PUSH_INTERVAL_MINUTES": "0"}
        code_hook, _ = self.run_hook(stdin='{"session_id": "d1491a9c-fa03-cli"}', env=env)
        code_manual, _ = self.run_hook(stdin="", env=env)
        self.assertEqual((code_hook, code_manual), (0, 0))
        self.assertEqual(len(FakePusher.instances), 2)  # 结构下限：两次都真的推送了
        source_ids = [instance.config.source_id for instance in FakePusher.instances]
        self.assertEqual(source_ids, ["claude-cloud-cse_013Qbc-test"] * 2)

    def test_pusher_gets_fixed_identity_and_session_source_id(self) -> None:
        code, _ = self.run_hook()
        self.assertEqual(code, 0)
        self.assertEqual(len(FakePusher.instances), 1)
        pusher = FakePusher.instances[0]
        self.assertTrue(pusher.pushed)
        config = pusher.config
        self.assertEqual(config.source_id, "claude-cloud-abc-123")
        self.assertEqual(config.machine, "claude-cloud")
        self.assertEqual(config.os_user, "claude-cloud")
        self.assertEqual(config.platform, "linux")
        self.assertEqual(config.token_env, "AI_USAGE_INGEST_TOKEN")
        self.assertEqual(config.server_url, "https://example.invalid/ingest")
        self.assertTrue(config.timezone)
        self.assertIsNone(config.outbox)

    def test_generated_config_passes_owner_validation_and_machine_ignores_hostname(self) -> None:
        raw = cloud_push.build_device_config("abc-123", "https://example.invalid/ingest", "Asia/Shanghai")
        config = validate_device_config(raw)
        self.assertEqual(config.machine, "claude-cloud")
        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertNotIn("AI_USAGE_INGEST_TOKEN", json.dumps(raw).replace('"token_env": "AI_USAGE_INGEST_TOKEN"', ""))


class TestCloudAccountFingerprint(CloudPushCase):
    """#208：容器内 ~/.claude.json 的 accountUuid 必须让云端与本机得到同一账户指纹。"""

    UUID = "11111111-2222-3333-4444-555555555555"

    def make_home(self, claude_json) -> Path:
        home = Path(self.tmp.name) / "home"
        home.mkdir(exist_ok=True)
        if claude_json is not None:
            (home / ".claude.json").write_text(json.dumps(claude_json), encoding="utf-8")
        return home

    def cloud_observations(self, home: Path) -> list:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            cloud_push.run(
                stdin_text='{"session_id": "abc-123"}', env=dict(ENV), state_path=self.state,
                now=NOW, pusher_factory=FakePusher, home=home,
            )
        self.assertEqual(len(FakePusher.instances), 1)
        return _account_observations(FakePusher.instances[0].config, NOW.isoformat())

    def test_cloud_observation_matches_independently_computed_and_local_fingerprint(self) -> None:
        home = self.make_home({"oauthAccount": {"accountUuid": self.UUID}})
        observations = self.cloud_observations(home)
        # 独立复算：不经 account_fingerprint 的读文件路径，直接按规格哈希。
        expected = "fp:claude:" + hashlib.sha256(f"aiusage-account-v1:claude:{self.UUID}".encode()).hexdigest()[:24]
        self.assertEqual(expected, compute_account_fingerprint("claude", self.UUID))
        self.assertEqual(len(observations), 1)  # 结构下限：恰好一条 claude 观察
        self.assertEqual(observations[0]["provider"], "claude")
        self.assertEqual(observations[0]["account_fingerprint"], expected)
        # 本机配置同样 uuid 显式给路径，推导结果一致。
        local_cfg = replace(
            validate_device_config(cloud_push.build_device_config("x", "https://example.invalid/ingest", "Asia/Shanghai")),
            account_fingerprint_sources={"claude": str(home / ".claude.json")},
        )
        self.assertEqual(_account_observations(local_cfg, NOW.isoformat())[0]["account_fingerprint"], expected)
        self.assertNotIn(self.UUID, json.dumps(observations))

    def test_config_declares_claude_json_path_from_injected_home(self) -> None:
        home = self.make_home(None)
        raw = cloud_push.build_device_config("abc", "https://example.invalid/ingest", "Asia/Shanghai", home=home)
        self.assertEqual(raw["account_fingerprint_sources"], {"claude": str(home / ".claude.json")})

    def test_missing_file_degrades_to_no_observation(self) -> None:
        self.assertEqual(self.cloud_observations(self.make_home(None)), [])

    def test_file_without_oauth_account_degrades_to_no_observation(self) -> None:
        self.assertEqual(self.cloud_observations(self.make_home({"theme": "dark"})), [])


class TestThrottleAndLookback(CloudPushCase):
    def test_first_push_runs_and_records_state(self) -> None:
        self.run_hook()
        self.assertEqual(len(FakePusher.instances), 1)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["source_id"], "claude-cloud-abc-123")
        self.assertEqual(state["last_success_at"], NOW.isoformat())

    def test_push_within_interval_is_skipped(self) -> None:
        self.run_hook(interval=10)
        code, _ = self.run_hook(now=NOW + timedelta(minutes=9, seconds=59), interval=10)
        self.assertEqual(code, 0)
        self.assertEqual(len(FakePusher.instances), 1, "第二次应被节流，不构造 pusher")

    def test_default_throttles_stop_to_15_minutes(self) -> None:
        """未设环境变量：1 分钟后的 Stop 被跳过，16 分钟后放行（#213：每次推送触发整天汇总重建）。"""
        self.assertEqual(cloud_push.DEFAULT_INTERVAL_MINUTES, 15.0)
        self.run_hook()
        self.run_hook(now=NOW + timedelta(minutes=1))
        self.assertEqual(len(FakePusher.instances), 1, "默认 15 分钟内第二次 Stop 应被跳过")
        self.run_hook(now=NOW + timedelta(minutes=16))
        self.assertEqual(len(FakePusher.instances), 2, "超过 15 分钟应放行")

    def test_env_zero_disables_throttle(self) -> None:
        env = dict(ENV, AI_USAGE_CLOUD_PUSH_INTERVAL_MINUTES="0")
        self.run_hook(env=env)
        self.run_hook(env=env, now=NOW + timedelta(minutes=1))
        self.run_hook(env=env, now=NOW + timedelta(minutes=1, seconds=5))
        self.assertEqual(len(FakePusher.instances), 3, "环境变量 0 = 不节流，每次 Stop 都推")

    def test_final_bypasses_throttle_and_records_state(self) -> None:
        self.run_hook()
        code, _ = self.run_hook(now=NOW + timedelta(minutes=1), final=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(FakePusher.instances), 2, "--final 一分钟后仍应推送")
        self.assertTrue(FakePusher.instances[1].pushed)
        self.assertEqual(
            json.loads(self.state.read_text())["last_success_at"], (NOW + timedelta(minutes=1)).isoformat()
        )

    def test_final_still_requires_token_url_and_session(self) -> None:
        for kwargs in ({"env": {"AI_USAGE_INGEST_URL": "https://example.invalid/ingest"}},
                       {"env": {"AI_USAGE_INGEST_TOKEN": "x"}}, {"stdin": ""}):
            code, output = self.run_hook(final=True, **kwargs)
            self.assertEqual((code, output), (0, ""))
        self.assertEqual(len(FakePusher.instances), 0)

    def test_push_after_interval_runs_again(self) -> None:
        self.run_hook(interval=10)
        self.run_hook(now=NOW + timedelta(minutes=10), interval=10)
        self.assertEqual(len(FakePusher.instances), 2)

    def test_interval_is_configurable_via_env(self) -> None:
        env = dict(ENV, AI_USAGE_CLOUD_PUSH_INTERVAL_MINUTES="1")
        self.run_hook(env=env)
        self.run_hook(env=env, now=NOW + timedelta(minutes=2))
        self.assertEqual(len(FakePusher.instances), 2)
        env = dict(ENV, AI_USAGE_CLOUD_PUSH_INTERVAL_MINUTES="30")
        self.run_hook(env=env, now=NOW + timedelta(minutes=20))
        self.assertEqual(len(FakePusher.instances), 2)

    def test_failed_push_does_not_start_throttle_window(self) -> None:
        FakePusher.result = {"success": False, "status": "server_error"}
        code, _ = self.run_hook(interval=10)
        self.assertEqual(code, 0)
        self.assertFalse(self.state.exists())
        FakePusher.result = {"success": False, "status": "server_error"}
        self.run_hook(now=NOW + timedelta(minutes=1), interval=10)
        self.assertEqual(len(FakePusher.instances), 2)

    def test_state_from_another_session_does_not_throttle(self) -> None:
        self.run_hook(interval=10)
        self.run_hook(stdin='{"session_id": "other"}', now=NOW + timedelta(minutes=1), interval=10)
        self.assertEqual(len(FakePusher.instances), 2)

    def test_lookback_first_push_is_capped_and_later_push_follows_last_success(self) -> None:
        self.run_hook()
        self.assertEqual(FakePusher.instances[0].kwargs["ledger_lookback_hours"], cloud_push.MAX_LOOKBACK_HOURS)
        self.assertEqual(FakePusher.instances[0].kwargs["ledger_mode"], "incremental")
        self.run_hook(now=NOW + timedelta(minutes=30))
        self.assertEqual(FakePusher.instances[1].kwargs["ledger_lookback_hours"], 2.0)
        self.run_hook(now=NOW + timedelta(hours=30))
        self.assertEqual(FakePusher.instances[2].kwargs["ledger_lookback_hours"], cloud_push.MAX_LOOKBACK_HOURS)

    def test_lookback_never_below_one_hour(self) -> None:
        self.assertGreaterEqual(cloud_push.lookback_hours(NOW, NOW), 1.0)


class TestSilentExit(CloudPushCase):
    def test_missing_token_exits_silently_without_pushing(self) -> None:
        code, output = self.run_hook(env={"AI_USAGE_INGEST_URL": "https://example.invalid/ingest"})
        self.assertEqual((code, output, len(FakePusher.instances)), (0, "", 0))

    def test_missing_server_url_exits_silently_without_pushing(self) -> None:
        code, output = self.run_hook(env={"AI_USAGE_INGEST_TOKEN": "x"})
        self.assertEqual((code, output, len(FakePusher.instances)), (0, "", 0))

    def test_missing_session_id_exits_silently(self) -> None:
        code, output = self.run_hook(stdin="")
        self.assertEqual((code, output, len(FakePusher.instances)), (0, "", 0))

    def test_pusher_exception_never_blocks_hook_and_does_not_leak_token(self) -> None:
        class Boom(FakePusher):
            def push(self):
                raise RuntimeError("boom " + ENV["AI_USAGE_INGEST_TOKEN"])

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cloud_push.run(
                stdin_text='{"session_id": "abc"}', env=dict(ENV), state_path=self.state,
                now=NOW, pusher_factory=Boom,
            )
        self.assertEqual(code, 0)
        self.assertNotIn(ENV["AI_USAGE_INGEST_TOKEN"], out.getvalue() + err.getvalue())
        self.assertFalse(self.state.exists())

    def test_cli_subcommand_is_wired_and_returns_zero_without_env(self) -> None:
        old = {k: os.environ.pop(k, None) for k in ENV}
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["cloud-push", "--state-file", str(self.state)]), 0)
        finally:
            for key, value in old.items():
                if value is not None:
                    os.environ[key] = value


class TestInstallHooks(unittest.TestCase):
    COMMAND = "/usr/local/bin/ai-usage-widget cloud-push"
    FINAL = COMMAND + " --final"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / ".claude" / "settings.json"

    def commands(self, event: str) -> list[str]:
        data = json.loads(self.settings.read_text())
        return [h["command"] for group in data["hooks"][event] for h in group["hooks"]]

    def test_creates_stop_and_session_end_when_missing(self) -> None:
        cloud_push.install_hooks(self.settings, self.COMMAND)
        self.assertEqual(self.commands("Stop"), [self.COMMAND])
        self.assertEqual(self.commands("SessionEnd"), [self.FINAL])

    def test_merge_preserves_existing_hooks_and_other_keys(self) -> None:
        self.settings.parent.mkdir(parents=True)
        existing = {
            "model": "sonnet",
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}],
                "SessionEnd": [{"hooks": [{"type": "command", "command": "echo bye"}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
            },
        }
        self.settings.write_text(json.dumps(existing))
        cloud_push.install_hooks(self.settings, self.COMMAND)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["model"], "sonnet")
        self.assertEqual(data["hooks"]["PreToolUse"], existing["hooks"]["PreToolUse"])
        self.assertEqual(self.commands("Stop"), ["echo mine", self.COMMAND])
        self.assertEqual(self.commands("SessionEnd"), ["echo bye", self.FINAL])

    def test_repeated_install_is_idempotent(self) -> None:
        cloud_push.install_hooks(self.settings, self.COMMAND)
        first = self.settings.read_text()
        cloud_push.install_hooks(self.settings, self.COMMAND)
        cloud_push.install_hooks(self.settings, self.COMMAND)
        self.assertEqual(self.settings.read_text(), first)
        self.assertEqual(self.commands("Stop").count(self.COMMAND), 1)
        self.assertEqual(self.commands("SessionEnd").count(self.FINAL), 1)

    def test_reinstall_with_new_path_updates_instead_of_duplicating(self) -> None:
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
        cloud_push.install_hooks(self.settings, "/old/bin/ai-usage-widget cloud-push")
        cloud_push.install_hooks(self.settings, self.COMMAND)
        self.assertEqual(self.commands("Stop"), ["echo mine", self.COMMAND])
        self.assertEqual(self.commands("SessionEnd"), [self.FINAL])

    def test_unparseable_settings_is_not_overwritten(self) -> None:
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("{not json")
        with self.assertRaises(ValueError):
            cloud_push.install_hooks(self.settings, self.COMMAND)
        self.assertEqual(self.settings.read_text(), "{not json")

    def test_cli_install_hook_writes_both_hooks(self) -> None:
        with redirect_stdout(io.StringIO()):
            code = cli.main(["cloud-push", "--install-hook", "--settings", str(self.settings)])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.commands("Stop")), 1)
        self.assertEqual(len(self.commands("SessionEnd")), 1)
        self.assertTrue(self.commands("Stop")[0].endswith("cloud-push"))
        self.assertTrue(self.commands("SessionEnd")[0].endswith("cloud-push --final"))

    def test_cli_final_flag_is_wired(self) -> None:
        old = {k: os.environ.pop(k, None) for k in ENV}
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["cloud-push", "--final"]), 0)
        finally:
            for key, value in old.items():
                if value is not None:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
