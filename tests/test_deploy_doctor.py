from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
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


# Issue 八类之外新增的 reason code。八类仍然一一对应、互不相同，
# 这些只是把原本被硬塞进八类的情况拆出来，避免结论互相污染。
EXPECTED_ADDITIONAL_EXIT_CODES = {
    "entry_redirected_to_portal": 12,
    "entry_route_unexpected": 17,
    "precheck_incomplete": 18,
}

HEALTH_JSON = json.dumps(
    {
        "status": "ok",
        "generated_at": "2026-08-01T12:00:00+08:00",
        "backend_mode": "origin_direct",
        "canonical_store": "origin_sqlite",
    }
)
LOGIN_PAGE_HTML = "<html><body>Sign in to continue</body></html>"


def _load_case(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"case_{name}.json").read_text(encoding="utf-8"))


class _RecordingServer:
    """本地回环 HTTP server，只用于固定 doctor 的传输层行为，不访问外网。"""

    def __init__(self, responder) -> None:
        self.requests: list[tuple[str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
                outer.requests.append((self.path, self.headers.get("Authorization")))
                responder(self)

            def log_message(self, *args) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _respond(handler, status: int, body: str, content_type: str, location: str | None = None) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    if location:
        handler.send_header("Location", location)
    handler.end_headers()
    handler.wfile.write(body.encode("utf-8"))


class EntryProbeTransportTests(unittest.TestCase):
    """P0-1 / P1-1：跨主机 302 既不能把 token 带走，也不能被当成健康。"""

    def setUp(self) -> None:
        self.idp = _RecordingServer(
            lambda handler: _respond(handler, 200, LOGIN_PAGE_HTML, "text/html")
        )
        self.addCleanup(self.idp.shutdown)
        idp_origin = self.idp.origin
        self.entry = _RecordingServer(
            lambda handler: _respond(
                handler, 302, "", "text/html", location=f"{idp_origin}/idp-login"
            )
        )
        self.addCleanup(self.entry.shutdown)

    def _probe(self) -> "deploy_doctor.EntryProbe":
        return deploy_doctor.default_probe(
            f"{self.entry.origin}/api/health",
            {"Authorization": "Bearer SUPER-SECRET-TOKEN", "User-Agent": "AIUsagePusher/1.0"},
            5.0,
        )

    def test_probe_never_forwards_authorization_to_the_redirect_target(self) -> None:
        self._probe()

        self.assertEqual(len(self.entry.requests), 1)
        self.assertEqual(self.entry.requests[0][1], "Bearer SUPER-SECRET-TOKEN")
        # 第三方 IdP / captive portal 绝不能拿到生产 ingest token。
        for path, authorization in self.idp.requests:
            self.assertIsNone(authorization, f"token leaked to redirect target at {path}")

    def test_probe_records_the_redirect_as_a_visible_fact(self) -> None:
        probe = self._probe()

        self.assertTrue(probe.redirected)
        self.assertIn("/idp-login", probe.redirect_location)
        self.assertEqual(probe.status, 302)

    def test_redirected_entry_is_never_reported_as_healthy(self) -> None:
        environment = deploy_doctor.DoctorEnvironment(
            device_config={"server_url": f"{self.entry.origin}/ingest"},
            entry_probe=self._probe(),
        )

        check = deploy_doctor._check_entry(environment)

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "entry_redirected_to_portal")
        self.assertEqual(deploy_doctor.exit_code_for_reason(check.reason_code), 12)
        self.assertNotIn("SUPER-SECRET-TOKEN", check.detail + check.remediation)


class EntryHealthContractTests(unittest.TestCase):
    """P1-1：200 必须真的是本产品的 /api/health 响应，不能是随便一个 200。"""

    def _check(self, status: int, body: str, headers: dict | None = None):
        environment = deploy_doctor.DoctorEnvironment(
            device_config={"server_url": "https://aiusage.example.invalid/ingest"},
            entry_probe=deploy_doctor.EntryProbe(
                url="https://aiusage.example.invalid/api/health",
                status=status,
                headers=headers or {"content-type": "application/json"},
                body=body,
            ),
        )
        return deploy_doctor._check_entry(environment)

    def test_real_health_payload_is_accepted(self) -> None:
        check = self._check(200, HEALTH_JSON)

        self.assertTrue(check.ok, check.detail)

    def test_200_login_page_is_rejected(self) -> None:
        check = self._check(200, LOGIN_PAGE_HTML, {"content-type": "text/html"})

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "entry_route_unexpected")

    def test_200_json_without_the_health_contract_is_rejected(self) -> None:
        check = self._check(200, json.dumps({"hello": "world"}))

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "entry_route_unexpected")

    def test_200_health_error_payload_is_rejected(self) -> None:
        check = self._check(200, json.dumps({"status": "error", "error_type": "auth_required"}))

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "entry_route_unexpected")


class EntryStatusClassificationTests(unittest.TestCase):
    """P1-2：收到了 HTTP 响应就不能叫「网络不可达」。"""

    def _reason(self, **probe_kwargs) -> str:
        environment = deploy_doctor.DoctorEnvironment(
            device_config={"server_url": "https://aiusage.example.invalid/ingest"},
            entry_probe=deploy_doctor.EntryProbe(
                url="https://aiusage.example.invalid/api/health", **probe_kwargs
            ),
        )
        return deploy_doctor._check_entry(environment).reason_code

    def test_404_is_a_route_problem_not_a_network_problem(self) -> None:
        self.assertEqual(self._reason(status=404, body="not found"), "entry_route_unexpected")

    def test_500_is_a_route_problem_not_a_network_problem(self) -> None:
        self.assertEqual(self._reason(status=500, body="boom"), "entry_route_unexpected")

    def test_429_without_guard_markers_is_a_route_problem(self) -> None:
        self.assertEqual(self._reason(status=429, body="slow down"), "entry_route_unexpected")

    def test_route_problem_has_its_own_exit_code(self) -> None:
        self.assertEqual(deploy_doctor.exit_code_for_reason("entry_route_unexpected"), 17)
        self.assertNotEqual(
            deploy_doctor.exit_code_for_reason("entry_route_unexpected"),
            deploy_doctor.exit_code_for_reason("network_unreachable"),
        )

    def test_no_response_at_all_is_still_network_unreachable(self) -> None:
        self.assertEqual(self._reason(status=None, error="URLError"), "network_unreachable")

    def test_403_is_still_an_entry_guard_problem(self) -> None:
        self.assertEqual(self._reason(status=403, body="blocked"), "entry_blocked_by_waf")

    def test_401_is_still_a_token_problem(self) -> None:
        self.assertEqual(self._reason(status=401, body="{}"), "auth_token_invalid")


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

    def test_additional_reason_codes_never_collide_with_the_eight(self) -> None:
        additional = set(deploy_doctor.ADDITIONAL_REASON_CODES)

        self.assertEqual(additional & EXPECTED_REASON_CODES, set())
        self.assertEqual(additional, set(EXPECTED_ADDITIONAL_EXIT_CODES))
        self.assertEqual(
            set(deploy_doctor.ALL_REASON_CODES),
            EXPECTED_REASON_CODES | additional,
        )
        self.assertEqual(len(deploy_doctor.ALL_REASON_CODES), 11)

    def test_every_reason_code_has_a_registered_exit_code(self) -> None:
        expected = {**EXPECTED_EXIT_CODES, **EXPECTED_ADDITIONAL_EXIT_CODES}
        actual = {
            reason: deploy_doctor.exit_code_for_reason(reason)
            for reason in deploy_doctor.ALL_REASON_CODES
        }

        self.assertEqual(actual, expected)

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


class DeviceIdentityNormalizationTests(unittest.TestCase):
    """身份判定必须沿用 config.py 的规范化口径，不能自己重定义，否则健康设备被误判。"""

    def _environment(self, **overrides) -> "deploy_doctor.DoctorEnvironment":
        fixture = _load_case("healthy")
        for key, value in overrides.items():
            if key == "device_config":
                fixture["device_config"] = {**fixture["device_config"], **value}
            else:
                fixture[key] = value
        return deploy_doctor.DoctorEnvironment.from_fixture(fixture)

    def test_mac_platform_alias_is_not_reported_as_an_identity_mismatch(self) -> None:
        environment = deploy_doctor.DoctorEnvironment.from_fixture(_load_case("healthy_mac"))

        report = deploy_doctor.diagnose(environment)

        self.assertTrue(report.ok, [check.detail for check in report.checks if not check.ok])

    def test_uppercase_platform_is_normalized_before_comparison(self) -> None:
        environment = self._environment(device_config={"platform": "Linux"})

        report = deploy_doctor.diagnose(environment)

        self.assertTrue(report.ok, [check.detail for check in report.checks if not check.ok])

    def test_config_without_machine_falls_back_to_the_observed_machine(self) -> None:
        fixture = _load_case("healthy")
        fixture["device_config"].pop("machine")
        environment = deploy_doctor.DoctorEnvironment.from_fixture(fixture)

        report = deploy_doctor.diagnose(environment)

        self.assertTrue(report.ok, [check.detail for check in report.checks if not check.ok])

    def test_unknown_os_user_is_still_an_identity_problem(self) -> None:
        environment = self._environment(device_config={"os_user": "unknown"})

        report = deploy_doctor.diagnose(environment)

        self.assertEqual(report.reason_code, "device_identity_mismatch")

    def test_unsupported_platform_is_still_an_identity_problem(self) -> None:
        environment = self._environment(device_config={"platform": "android"})

        report = deploy_doctor.diagnose(environment)

        self.assertEqual(report.reason_code, "device_identity_mismatch")


class TimerScopeTests(unittest.TestCase):
    """BIAI 现网采集 timer 是 system-level 的，写死 --user 会把健康 timer 判成坏的。"""

    def _collect(self, scope: str, show_output: str = "") -> tuple[list, "deploy_doctor.DoctorEnvironment"]:
        recorded: list[list[str]] = []

        def runner(argv):
            recorded.append(list(argv))
            return show_output

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_id": "linux-biai-wangzp",
                        "machine": "biai-collector-01",
                        "os_user": "wangzp",
                        "platform": "linux",
                        "timezone": "Asia/Shanghai",
                        "server_url": "https://aiusage.example.invalid/ingest",
                    }
                ),
                encoding="utf-8",
            )
            environment = deploy_doctor.collect_environment(
                config_path=str(config_path),
                timer_unit="ai-usage-pusher-linux-biai-wangzp.timer",
                timer_scope=scope,
                env={},
                probe=lambda url, headers, timeout: deploy_doctor.EntryProbe(url=url, status=200),
                command_runner=runner,
            )
        return recorded, environment

    def test_user_scope_queries_the_user_manager(self) -> None:
        recorded, _ = self._collect("user")

        self.assertEqual(recorded[0][:3], ["systemctl", "--user", "show"])

    def test_system_scope_queries_the_system_manager(self) -> None:
        recorded, _ = self._collect("system")

        self.assertEqual(recorded[0][:3], ["systemctl", "--system", "show"])

    def test_disabled_timer_remediation_uses_the_configured_scope(self) -> None:
        environment = deploy_doctor.DoctorEnvironment(
            device_config={},
            timer_unit="ai-usage-pusher-linux-biai-wangzp.timer",
            timer_scope="system",
            timer_properties={
                "LoadState": "loaded",
                "UnitFileState": "disabled",
                "NextElapseUSecRealtime": "n/a",
            },
        )

        check = deploy_doctor._check_timer(environment)

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "timer_without_future_trigger")
        self.assertIn("system", check.detail)
        self.assertIn(
            "systemctl --system enable --now ai-usage-pusher-linux-biai-wangzp.timer",
            check.remediation,
        )
        self.assertNotIn("--user", check.remediation)

    def test_unit_missing_in_the_selected_scope_points_at_the_scope(self) -> None:
        _, environment = self._collect(
            "user", show_output="LoadState=not-found\nUnitFileState=\nActiveState=inactive\n"
        )

        report = deploy_doctor.diagnose(environment)

        # 这里跑在真实机器上，身份检查会不会失败取决于本机 hostname，
        # 所以只断言被测的 timer 检查本身。
        timer_check = next(check for check in report.checks if check.name == "timer_schedule")
        self.assertFalse(timer_check.ok)
        self.assertEqual(timer_check.reason_code, "timer_without_future_trigger")
        self.assertIn("user", timer_check.detail)
        self.assertIn("--timer-scope", timer_check.remediation)


class UnitPythonPathTests(unittest.TestCase):
    """P1-3：要检查的是 timer 那个 unit 里的 PYTHONPATH，不是操作者 shell 里的。"""

    def _environment(self, **overrides) -> "deploy_doctor.DoctorEnvironment":
        defaults = dict(
            device_config={},
            release_dir="/opt/ai-usage/current",
            timer_unit="ai-usage-pusher.timer",
            unit_environment={"PYTHONPATH": "/opt/ai-usage/current/src"},
            unit_pythonpath_package_roots=["/opt/ai-usage/current/src"],
        )
        defaults.update(overrides)
        return deploy_doctor.DoctorEnvironment(**defaults)

    def test_unit_pythonpath_matching_the_release_dir_is_ok(self) -> None:
        check = deploy_doctor._check_pythonpath(self._environment())

        self.assertTrue(check.ok, check.detail)

    def test_unit_pythonpath_pointing_at_a_stale_tree_is_a_mismatch(self) -> None:
        check = deploy_doctor._check_pythonpath(
            self._environment(
                unit_environment={"PYTHONPATH": "/home/wangzp/ai-usage-widget/src"},
                unit_pythonpath_package_roots=["/home/wangzp/ai-usage-widget/src"],
            )
        )

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "pythonpath_import_mismatch")
        self.assertIn("/opt/ai-usage/current/src", check.detail)

    def test_unit_pythonpath_without_an_importable_package_is_a_mismatch(self) -> None:
        check = deploy_doctor._check_pythonpath(
            self._environment(unit_pythonpath_package_roots=[])
        )

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "pythonpath_import_mismatch")

    def test_operator_shell_pythonpath_is_not_used_when_the_unit_is_known(self) -> None:
        # 操作者 shell 里手敲对了，不能掩盖 unit 里写错的那一份。
        check = deploy_doctor._check_pythonpath(
            self._environment(
                unit_environment={"PYTHONPATH": "/home/wangzp/stale/src"},
                unit_pythonpath_package_roots=["/home/wangzp/stale/src"],
                python_path=["/opt/ai-usage/current/src"],
                imported_from="/opt/ai-usage/current/src/ai_usage_widget/__init__.py",
            )
        )

        self.assertFalse(check.ok)
        self.assertEqual(check.reason_code, "pythonpath_import_mismatch")

    def test_unreadable_unit_environment_is_unknown_not_ok(self) -> None:
        check = deploy_doctor._check_pythonpath(
            self._environment(unit_environment=None, unit_pythonpath_package_roots=[])
        )

        self.assertFalse(check.ok)
        self.assertEqual(check.status, "unknown")
        self.assertEqual(check.reason_code, "precheck_incomplete")

    def test_unit_without_pythonpath_is_ok_because_the_package_is_installed(self) -> None:
        check = deploy_doctor._check_pythonpath(
            self._environment(unit_environment={}, unit_pythonpath_package_roots=[])
        )

        self.assertTrue(check.ok, check.detail)

    def test_without_a_timer_unit_the_check_is_skipped_not_silently_green(self) -> None:
        check = deploy_doctor._check_pythonpath(
            deploy_doctor.DoctorEnvironment(device_config={})
        )

        self.assertEqual(check.status, "skipped")

    def test_collect_environment_reads_the_service_unit_environment(self) -> None:
        recorded: list[list[str]] = []

        def runner(argv):
            recorded.append(list(argv))
            if "ai-usage-pusher.service" in argv:
                return "Environment=PYTHONPATH=/opt/ai-usage/current/src LANG=C\n"
            return "LoadState=loaded\nUnitFileState=enabled\nNextElapseUSecRealtime=Sat\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(
                json.dumps(
                    {
                        "source_id": "s",
                        "os_user": "u",
                        "platform": "linux",
                        "timezone": "UTC",
                        "server_url": "https://aiusage.example.invalid/ingest",
                    }
                ),
                encoding="utf-8",
            )
            environment = deploy_doctor.collect_environment(
                config_path=str(config_path),
                timer_unit="ai-usage-pusher.timer",
                env={},
                probe=lambda url, headers, timeout: deploy_doctor.EntryProbe(url=url, status=200),
                command_runner=runner,
            )

        self.assertTrue(
            any("ai-usage-pusher.service" in argv for argv in recorded),
            recorded,
        )
        self.assertEqual(environment.unit_environment, {"PYTHONPATH": "/opt/ai-usage/current/src", "LANG": "C"})


class UnknownCheckAggregationTests(unittest.TestCase):
    def test_an_unknown_check_makes_the_report_not_ok_with_its_own_exit_code(self) -> None:
        fixture = _load_case("healthy")
        fixture["timer"]["unit"] = "ai-usage-pusher.timer"
        fixture["unit_environment"] = None
        environment = deploy_doctor.DoctorEnvironment.from_fixture(fixture)

        report = deploy_doctor.diagnose(environment)

        self.assertFalse(report.ok)
        self.assertEqual(report.reason_code, "precheck_incomplete")
        self.assertEqual(report.exit_code, 18)
        self.assertIn("pythonpath_alignment", report.to_dict()["unknown_checks"])

    def test_a_real_failure_outranks_an_unknown_check(self) -> None:
        fixture = _load_case("entry_blocked_by_waf")
        fixture["unit_environment"] = None
        environment = deploy_doctor.DoctorEnvironment.from_fixture(fixture)

        report = deploy_doctor.diagnose(environment)

        self.assertEqual(report.reason_code, "entry_blocked_by_waf")


class MacTimerBoundaryTests(unittest.TestCase):
    """P1-4：Mac 上没有 systemd，doctor 既不能崩，也不能假装检查过了。"""

    def test_mac_fixture_never_claims_systemd_only_properties(self) -> None:
        fixture = _load_case("healthy_mac")
        serialized = json.dumps(fixture)

        for systemd_only in ("LoadState", "UnitFileState", "NextElapseUSec"):
            self.assertNotIn(systemd_only, serialized)

    def test_darwin_timer_check_is_an_explicit_unknown(self) -> None:
        environment = deploy_doctor.DoctorEnvironment(
            device_config={"platform": "darwin"},
            timer_unit="com.chunbai.aiusage.pusher.mac-wangzhipeng",
            timer_supported=False,
        )

        check = deploy_doctor._check_timer(environment)

        self.assertEqual(check.status, "unknown")
        self.assertEqual(check.reason_code, "precheck_incomplete")
        self.assertIn("launchd", check.detail)

    def test_collect_environment_on_darwin_does_not_shell_out_to_systemctl(self) -> None:
        calls: list[list[str]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(
                json.dumps(
                    {
                        "source_id": "mac",
                        "os_user": "wangzhipeng",
                        "platform": "mac",
                        "timezone": "Asia/Shanghai",
                        "server_url": "https://aiusage.example.invalid/ingest",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(deploy_doctor.sys, "platform", "darwin"):
                environment = deploy_doctor.collect_environment(
                    config_path=str(config_path),
                    timer_unit="com.chunbai.aiusage.pusher.mac",
                    env={},
                    probe=lambda url, headers, timeout: deploy_doctor.EntryProbe(url=url, status=200),
                    command_runner=lambda argv: calls.append(list(argv)) or "",
                )

        self.assertEqual(calls, [])
        self.assertFalse(environment.timer_supported)

    def test_a_systemctl_that_does_not_exist_is_unknown_not_doctor_failed(self) -> None:
        def runner(argv):
            raise FileNotFoundError("systemctl")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(
                json.dumps(
                    {
                        "source_id": "s",
                        "os_user": "u",
                        "platform": "linux",
                        "timezone": "UTC",
                        "server_url": "https://aiusage.example.invalid/ingest",
                    }
                ),
                encoding="utf-8",
            )
            environment = deploy_doctor.collect_environment(
                config_path=str(config_path),
                timer_unit="ai-usage-pusher.timer",
                env={},
                probe=lambda url, headers, timeout: deploy_doctor.EntryProbe(url=url, status=200),
                command_runner=runner,
            )

        check = deploy_doctor._check_timer(environment)
        self.assertEqual(check.status, "unknown")


class DoctorPreconditionTests(unittest.TestCase):
    def test_doctor_refuses_to_run_without_a_usable_server_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(
                json.dumps({"source_id": "x", "os_user": "wangzp", "platform": "linux"}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as context:
                deploy_doctor.run_deploy_doctor(config_path=str(config_path), env={})

        self.assertIn("server_url", str(context.exception))

    def test_cli_reports_doctor_failed_instead_of_a_misleading_network_verdict(self) -> None:
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "device.json"
            config_path.write_text(json.dumps({"source_id": "x"}), encoding="utf-8")

            with redirect_stdout(buffer):
                code = cli.main(["doctor", "--config", str(config_path)])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, deploy_doctor.EXIT_DOCTOR_ERROR)
        self.assertEqual(payload["reason_code"], "doctor_failed")
        self.assertNotEqual(code, EXPECTED_EXIT_CODES["network_unreachable"])
        # 说不出哪里错的诊断等于没诊断。
        self.assertIn("server_url", payload["detail"])

    def test_tz_with_a_leading_colon_is_still_a_valid_timezone_name(self) -> None:
        self.assertEqual(deploy_doctor._system_timezone({"TZ": ":Asia/Shanghai"}), "Asia/Shanghai")


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

    def test_fixture_replay_also_masks_declared_secret_values(self) -> None:
        """P2：`--environment-fixture` 回放路径的遮蔽此前是失效的。"""
        fixture = _load_case("healthy")
        fixture["secret_values"] = [FAKE_TOKEN]
        environment = deploy_doctor.DoctorEnvironment.from_fixture(fixture)

        self.assertEqual(environment.secret_values, (FAKE_TOKEN,))
        report = deploy_doctor.DoctorReport(
            ok=False,
            reason_code="auth_token_invalid",
            exit_code=13,
            checks=(
                deploy_doctor.DoctorCheck(
                    name="entry_reachability",
                    ok=False,
                    reason_code="auth_token_invalid",
                    detail=f"token={FAKE_TOKEN}",
                ),
            ),
            secret_values=environment.secret_values,
        )
        self.assertNotIn(FAKE_TOKEN, json.dumps(report.to_dict(), ensure_ascii=False))

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
