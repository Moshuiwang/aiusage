from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ai_usage_widget import cli, deploy_doctor


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "deploy_doctor"

# Issue #57「验证契约」第 1 条列出的八类部署问题。
# 每一类必须有一个唯一的机器可读 reason code，才可能被脚本或上层流程判定。
EXPECTED_REASON_CODES = {
    "entry_blocked_by_waf",
    "auth_token_invalid",
    "network_unreachable",
    "timezone_mismatch",
    "device_identity_mismatch",
    "runtime_release_unversioned",
    "pythonpath_import_mismatch",
    "timer_without_future_trigger",
}

# 退出码按「用户下一步该做什么」分组：不要求八类全不同，
# 但入口拦截和 token 无效必须分开，否则会把用户引去轮换 token。
EXPECTED_EXIT_CODES = {
    "network_unreachable": 11,
    "entry_blocked_by_waf": 12,
    "auth_token_invalid": 13,
    "device_identity_mismatch": 14,
    "timezone_mismatch": 14,
    "runtime_release_unversioned": 15,
    "pythonpath_import_mismatch": 15,
    "timer_without_future_trigger": 16,
}


def _load_case(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"case_{name}.json").read_text(encoding="utf-8"))


class DeployDoctorReasonCodeTests(unittest.TestCase):
    def test_eight_diagnostic_reason_codes_are_distinct(self) -> None:
        codes = deploy_doctor.DIAGNOSTIC_REASON_CODES

        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
        self.assertEqual(set(codes), EXPECTED_REASON_CODES)
        self.assertNotIn(deploy_doctor.REASON_OK, codes)

    def test_every_offline_fixture_maps_to_its_own_reason_code(self) -> None:
        observed = []
        for name in sorted(EXPECTED_REASON_CODES):
            with self.subTest(case=name):
                fixture = _load_case(name)
                environment = deploy_doctor.DoctorEnvironment.from_fixture(fixture)

                report = deploy_doctor.diagnose(environment)

                self.assertFalse(report.ok)
                self.assertEqual(report.reason_code, fixture["expected_reason_code"])
                failed = [check.reason_code for check in report.checks if not check.ok]
                self.assertEqual(failed, [fixture["expected_reason_code"]])
                observed.append(report.reason_code)

        self.assertEqual(len(set(observed)), 8)

    def test_healthy_fixture_reports_ok_and_exit_zero(self) -> None:
        environment = deploy_doctor.DoctorEnvironment.from_fixture(_load_case("healthy"))

        report = deploy_doctor.diagnose(environment)

        self.assertTrue(report.ok, [check.detail for check in report.checks if not check.ok])
        self.assertEqual(report.reason_code, deploy_doctor.REASON_OK)
        self.assertEqual(report.exit_code, 0)

    def test_entry_block_and_invalid_token_use_different_exit_codes(self) -> None:
        blocked = deploy_doctor.exit_code_for_reason("entry_blocked_by_waf")
        invalid_token = deploy_doctor.exit_code_for_reason("auth_token_invalid")

        self.assertNotEqual(blocked, invalid_token)
        self.assertNotEqual(blocked, 0)
        self.assertNotEqual(invalid_token, 0)

    def test_exit_codes_group_by_remediation_category(self) -> None:
        actual = {
            reason: deploy_doctor.exit_code_for_reason(reason)
            for reason in EXPECTED_REASON_CODES
        }

        self.assertEqual(actual, EXPECTED_EXIT_CODES)
        self.assertEqual(deploy_doctor.exit_code_for_reason(deploy_doctor.REASON_OK), 0)

    def test_network_block_and_auth_reasons_are_three_separate_categories(self) -> None:
        categories = {
            deploy_doctor.category_for_reason(reason)
            for reason in ("network_unreachable", "entry_blocked_by_waf", "auth_token_invalid")
        }

        self.assertEqual(len(categories), 3)


class DeployDoctorCliTests(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_doctor_subcommand_replays_offline_fixture_with_reason_exit_code(self) -> None:
        for name in sorted(EXPECTED_REASON_CODES):
            with self.subTest(case=name):
                fixture_path = FIXTURES_DIR / f"case_{name}.json"

                code, payload = self._run_cli(
                    ["doctor", "--environment-fixture", str(fixture_path)]
                )

                self.assertEqual(payload["reason_code"], name)
                self.assertFalse(payload["ok"])
                self.assertEqual(code, EXPECTED_EXIT_CODES[name])
                self.assertEqual(payload["exit_code"], code)

    def test_doctor_subcommand_returns_zero_for_healthy_fixture(self) -> None:
        fixture_path = FIXTURES_DIR / "case_healthy.json"

        code, payload = self._run_cli(["doctor", "--environment-fixture", str(fixture_path)])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reason_code"], "ok")


FAKE_TOKEN = "fake-ingest-token-DO-NOT-LEAK-9f3a"
FAKE_URL_PASSWORD = "sup3r-secret-url-password"


class DeployDoctorReadOnlyTests(unittest.TestCase):
    """Issue #57 第 2 条：doctor 全程只读，且输出里不出现任何凭据值。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        (self.root / "config").mkdir()
        (self.root / "secrets").mkdir()
        (self.root / "releases" / "2026-08-01").mkdir(parents=True)
        (self.root / "data").mkdir()

        self.config_path = self.root / "config" / "device.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_id": "linux-biai-wangzp",
                    "host": "aiusage.example.invalid",
                    "machine": "biai-collector-01",
                    "os_user": "wangzp",
                    "platform": "linux",
                    "timezone": "Asia/Shanghai",
                    "server_url": (
                        f"https://collector:{FAKE_URL_PASSWORD}@aiusage.example.invalid/ingest"
                    ),
                    "timeout_seconds": 30,
                    "token_env": "AI_USAGE_DOCTOR_TEST_TOKEN",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.root / "secrets" / "ingest.env").write_text(
            f"AI_USAGE_DOCTOR_TEST_TOKEN={FAKE_TOKEN}\n", encoding="utf-8"
        )
        (self.root / "releases" / "2026-08-01" / "release.json").write_text(
            json.dumps({"version": "2026.08.01-1", "revision": "06fa591"}), encoding="utf-8"
        )
        (self.root / "data" / "usage.sqlite").write_bytes(b"SQLite format 3\x00fixture")

        self.env = {
            "AI_USAGE_DOCTOR_TEST_TOKEN": FAKE_TOKEN,
            "PYTHONPATH": str(self.root / "releases" / "2026-08-01" / "src"),
            "TZ": "Asia/Shanghai",
        }
        self.probe_calls: list[tuple[str, dict]] = []

    def _probe(self, status: int = 401, body: str = "", headers: dict | None = None):
        def probe(url: str, request_headers, timeout: float):
            self.probe_calls.append((url, dict(request_headers)))
            return deploy_doctor.EntryProbe(
                url=url,
                status=status,
                headers=headers or {"content-type": "application/json"},
                body=body,
            )

        return probe

    def _snapshot(self) -> dict:
        state = {}
        for path in sorted(self.root.rglob("*")):
            relative = str(path.relative_to(self.root))
            if path.is_dir():
                state[relative] = "dir"
                continue
            stat = path.stat()
            state[relative] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.st_size,
                stat.st_mtime_ns,
            )
        return state

    def _run(self, **kwargs):
        return deploy_doctor.run_deploy_doctor(
            config_path=str(self.config_path),
            release_dir=str(self.root / "releases" / "2026-08-01"),
            timer_unit="ai-usage-pusher.timer",
            env=self.env,
            probe=kwargs.pop("probe", None) or self._probe(),
            command_runner=lambda argv: (
                "LoadState=loaded\nUnitFileState=enabled\n"
                "NextElapseUSecRealtime=Sat 2026-08-01 12:30:00 CST\n"
            ),
            **kwargs,
        )

    def test_doctor_leaves_every_file_under_the_deployment_root_untouched(self) -> None:
        before = self._snapshot()

        self._run()

        self.assertEqual(self._snapshot(), before)

    def test_doctor_report_never_contains_the_token_value(self) -> None:
        report = self._run()

        serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(FAKE_TOKEN, serialized)
        # 报告仍然要有用：给出环境变量名，让用户知道去哪里换 token。
        self.assertIn("AI_USAGE_DOCTOR_TEST_TOKEN", serialized)
        self.assertEqual(report.reason_code, "auth_token_invalid")

    def test_doctor_report_redacts_credentials_embedded_in_the_server_url(self) -> None:
        report = self._run()

        serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(FAKE_URL_PASSWORD, serialized)
        self.assertIn("aiusage.example.invalid", serialized)

    def test_doctor_report_never_echoes_the_probe_response_body(self) -> None:
        leaked_body = f'{{"echoed":"{FAKE_TOKEN}"}}'

        report = self._run(probe=self._probe(status=401, body=leaked_body))

        serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(FAKE_TOKEN, serialized)
        self.assertNotIn("echoed", serialized)

    def test_doctor_probes_the_read_only_health_endpoint_instead_of_ingest(self) -> None:
        self._run()

        self.assertEqual(len(self.probe_calls), 1)
        url, headers = self.probe_calls[0]
        self.assertTrue(url.endswith("/api/health"), url)
        self.assertNotIn("/ingest", url)
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_TOKEN}")

    def test_report_masks_secret_values_even_when_a_check_leaks_one(self) -> None:
        """凭据不外泄必须是报告层的保证，而不是每个检查各自小心的巧合。"""
        leaking_check = deploy_doctor.DoctorCheck(
            name="entry_reachability",
            ok=False,
            reason_code="auth_token_invalid",
            detail=f"服务端拒绝了 token={FAKE_TOKEN}",
            remediation=f"轮换 {FAKE_TOKEN}",
        )
        report = deploy_doctor.DoctorReport(
            ok=False,
            reason_code="auth_token_invalid",
            exit_code=13,
            checks=(leaking_check,),
            secret_values=(FAKE_TOKEN,),
        )

        serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)

        self.assertNotIn(FAKE_TOKEN, serialized)
        self.assertIn("***", serialized)

    def test_collected_report_carries_the_token_value_as_a_masked_secret(self) -> None:
        report = self._run()

        self.assertIn(FAKE_TOKEN, report.secret_values)
        self.assertIn(FAKE_URL_PASSWORD, report.secret_values)

    def test_doctor_cli_writes_nothing_and_prints_no_credentials(self) -> None:
        before = self._snapshot()
        stdout, stderr = io.StringIO(), io.StringIO()
        offline_probe = lambda url, headers, timeout: deploy_doctor.EntryProbe(
            url=url, error="URLError"
        )

        with mock.patch.dict(os.environ, self.env, clear=False):
            with mock.patch.object(deploy_doctor, "default_probe", offline_probe):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "doctor",
                            "--config",
                            str(self.config_path),
                            "--release-dir",
                            str(self.root / "releases" / "2026-08-01"),
                        ]
                    )

        self.assertEqual(self._snapshot(), before)
        self.assertNotIn(FAKE_TOKEN, stdout.getvalue())
        self.assertNotIn(FAKE_TOKEN, stderr.getvalue())
        self.assertNotIn(FAKE_URL_PASSWORD, stdout.getvalue())
        self.assertNotIn(FAKE_URL_PASSWORD, stderr.getvalue())
        # 无网络的测试环境里探测必然失败，但那属于网络类而不是认证类。
        self.assertEqual(code, EXPECTED_EXIT_CODES["network_unreachable"])


class SystemctlShowParserTests(unittest.TestCase):
    def test_parses_enabled_timer_with_future_realtime_elapse(self) -> None:
        text = (
            "LoadState=loaded\n"
            "UnitFileState=enabled\n"
            "NextElapseUSecRealtime=Sat 2026-08-01 12:30:00 CST\n"
            "NextElapseUSecMonotonic=0\n"
        )

        properties = deploy_doctor.parse_systemctl_show(text)

        self.assertEqual(properties["UnitFileState"], "enabled")
        self.assertEqual(properties["NextElapseUSecRealtime"], "Sat 2026-08-01 12:30:00 CST")

    def test_treats_na_next_elapse_as_no_future_trigger(self) -> None:
        text = (
            "LoadState=loaded\n"
            "UnitFileState=enabled\n"
            "NextElapseUSecRealtime=n/a\n"
            "NextElapseUSecMonotonic=n/a\n"
        )

        properties = deploy_doctor.parse_systemctl_show(text)

        self.assertFalse(deploy_doctor.has_future_trigger(properties))

    def test_monotonic_only_timer_still_counts_as_future_trigger(self) -> None:
        text = (
            "LoadState=loaded\n"
            "UnitFileState=enabled\n"
            "NextElapseUSecRealtime=n/a\n"
            "NextElapseUSecMonotonic=15min 3s\n"
        )

        properties = deploy_doctor.parse_systemctl_show(text)

        self.assertTrue(deploy_doctor.has_future_trigger(properties))


if __name__ == "__main__":
    unittest.main()
