"""Issue #60 离线部分：`verify-cloud` 只读核对 CLI。

全部用例都用 `tests/fixtures/verify_cloud/<scenario>/` 下的离线 fixture 重放：
无网络、无真实凭据。fixture 的 mobile DTO 由 `mobile_summary.build_mobile_summary`
从同一份 summary 生成（见 `TestVerifyCloudFixturesStayBoundToReadModel`），
所以「两端口径一致」不是手写出来的巧合。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ai_usage_widget import cli, verify_cloud


FIXTURES = Path(__file__).parent / "fixtures" / "verify_cloud"
HEALTHY = FIXTURES / "healthy"
DEGRADED = FIXTURES / "degraded"
PARITY_MISMATCH = FIXTURES / "parity_mismatch"


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑一次 CLI，返回 (退出码, stdout, stderr)。"""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def copy_scenario(scenario: Path, mutate=None) -> str:
    """把一个场景复制到临时目录，可选地改写 summary.json 后返回目录路径。"""
    directory = tempfile.mkdtemp(prefix="verify-cloud-")
    for name in ("summary.json", "mobile_summary.json", "health.json"):
        shutil.copy(scenario / name, Path(directory) / name)
    if mutate is not None:
        target = Path(directory) / "summary.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        mutate(payload)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return directory


class TestVerifyCloudSummary(unittest.TestCase):
    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_healthy_period_totals_are_printed_and_exit_code_is_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("today", out)
        self.assertIn("2026-06-03", out)
        self.assertIn("900000", out)
        self.assertIn("120000", out)
        self.assertIn("80000", out)
        self.assertIn("claude", out)
        self.assertIn("codex", out)
        self.assertIn("complete", out)
        self.assertIn("核对通过", out)

    def test_partial_attribution_exits_data_issue_and_names_every_leftover_bucket(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("partial", out)
        self.assertIn("60000", out)
        self.assertIn("40000", out)
        self.assertIn("usage_attribution_partial", out)
        self.assertNotIn("核对通过", out)

    def test_missing_coverage_block_is_a_data_issue_not_a_silent_zero(self) -> None:
        directory = self._scenario(HEALTHY, lambda payload: payload.pop("provider_usage_coverage"))

        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("provider_usage_coverage_missing", out)

    def test_requested_period_that_the_read_model_did_not_honour_is_reported(self) -> None:
        code, out, _ = run_cli([
            "verify-cloud", "summary", "--fixture-dir", str(HEALTHY), "--period", "week",
        ])

        self.assertEqual(code, 3)
        self.assertIn("period_mismatch", out)

    def test_requested_period_that_matches_keeps_exit_code_ok(self) -> None:
        code, _, _ = run_cli([
            "verify-cloud", "summary", "--fixture-dir", str(HEALTHY),
            "--period", "today", "--date", "2026-06-03",
        ])

        self.assertEqual(code, 0)

    def test_json_output_is_machine_decidable(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(HEALTHY), "--json"])

        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["command"], "summary")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["totals"]["total_tokens"], 900000)
        self.assertEqual(
            [row["provider"] for row in report["provider_slots"]],
            ["claude", "codex", "antigravity"],
        )
        self.assertEqual(report["coverage"]["status"], "complete")


class TestVerifyCloudLimits(unittest.TestCase):
    """额度输出必须让「可信官方额度」和「降级态」一眼可分（AGENTS.md 官方额度不变量）。"""

    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_all_official_windows_are_marked_trusted_and_exit_code_is_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("可信官方额度", out)
        self.assertNotIn("降级", out)
        self.assertIn("42.0", out)
        self.assertIn("2026-06-08T00:00:00+08:00", out)

    def test_every_degraded_confidence_and_status_is_labelled_and_exits_data_issue(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("可信官方额度", out)
        self.assertIn("降级", out)
        for reason in ("confidence_estimated", "confidence_missing", "status_unsupported"):
            with self.subTest(reason=reason):
                self.assertIn(reason, out)

    def test_degraded_windows_never_print_percentages_or_reset_time(self) -> None:
        """降级窗口的百分比和 reset 时间一律不展示，否则本地估算会冒充官方额度。"""
        _, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertNotIn("61.0", out)
        self.assertNotIn("39.0", out)
        self.assertIn("42.0", out)

    def test_trusted_and_degraded_rows_carry_different_verdicts_in_json(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 3)
        self.assertEqual(report["command"], "limits")
        self.assertEqual(report["status"], "data_issue")
        self.assertEqual(report["trusted_count"], 1)
        self.assertEqual(report["degraded_count"], 3)

        by_key = {(row["provider"], row["window"]): row for row in report["windows"]}
        trusted = by_key[("claude", "week")]
        self.assertEqual(trusted["trust"], "trusted_official")
        self.assertEqual(trusted["degrade_reasons"], [])
        self.assertEqual(trusted["used_percent"], 42.0)
        self.assertEqual(trusted["reset_at"], "2026-06-08T00:00:00+08:00")

        estimated = by_key[("codex", "5h-block")]
        self.assertEqual(estimated["trust"], "degraded")
        self.assertIn("confidence_estimated", estimated["degrade_reasons"])
        self.assertIsNone(estimated["used_percent"])
        self.assertIsNone(estimated["remaining_percent"])
        self.assertIsNone(estimated["reset_at"])

        failed = by_key[("claude", "unknown")]
        self.assertIn("confidence_missing", failed["degrade_reasons"])
        self.assertIn("status_provider_failed", failed["degrade_reasons"])

        unsupported = by_key[("codex", "unknown")]
        self.assertIn("status_unsupported", unsupported["degrade_reasons"])

    def test_healthy_json_keeps_every_window_trusted(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["degraded_count"], 0)
        self.assertEqual(report["trusted_count"], 3)
        self.assertEqual(report["issues"], [])
        self.assertEqual(
            sorted(row["trust"] for row in report["windows"]),
            ["trusted_official", "trusted_official", "trusted_official"],
        )

    def test_provider_without_usable_quota_is_named(self) -> None:
        _, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertIn("provider_quota_unavailable", out)

    def test_empty_limit_list_is_a_data_issue_not_a_pass(self) -> None:
        directory = self._scenario(HEALTHY, lambda payload: payload.update({"limits": []}))

        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("limit_windows_missing", out)


class TestVerifyCloudHealth(unittest.TestCase):
    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_all_sources_fresh_prints_last_report_time_and_exits_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("linux-dev-wang", out)
        self.assertIn("mac-air-wang", out)
        self.assertIn("2026-06-03T11:58:00+08:00", out)
        self.assertIn("verified", out)
        self.assertIn("current", out)
        self.assertIn("核对通过", out)

    def test_stale_and_never_seen_sources_exit_data_issue_and_are_named(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("stale", out)
        self.assertIn("never_seen", out)
        self.assertIn("source_not_ok", out)
        self.assertIn("collector_version_unsupported", out)

    def test_output_never_leaks_server_filesystem_paths(self) -> None:
        """`/api/health` 带 database.path / snapshot.path，核对输出不得把它们透出去。"""
        for extra in ([], ["--json"]):
            with self.subTest(extra=extra):
                _, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY), *extra])
                self.assertNotIn("data/usage.sqlite", out)
                self.assertNotIn("data/latest.json", out)
                self.assertNotIn(".sqlite", out)

    def test_json_output_covers_freshness_coverage_and_accuracy(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["command"], "health")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source_total"], 2)
        self.assertEqual(report["status_counts"], {"ok": 2})
        self.assertEqual(report["limits_health"]["effective_window_count"], 2)

        rows = {row["source_id"]: row for row in report["sources"]}
        linux = rows["linux-dev-wang"]
        self.assertEqual(linux["status"], "ok")
        self.assertEqual(linux["last_observed_at"], "2026-06-03T11:58:00+08:00")
        self.assertEqual(linux["accuracy_status"], "verified")
        self.assertEqual(linux["version_state"], "current")
        self.assertEqual(
            linux["coverage"],
            [{
                "agent": "claude",
                "status": "verified",
                "start": "2026-06-01T00:00:00+08:00",
                "end": "2026-06-03T11:58:00+08:00",
            }],
        )

    def test_source_count_disagreement_between_endpoints_is_reported(self) -> None:
        directory = self._scenario(
            HEALTHY,
            lambda payload: payload.__setitem__("source_status", payload["source_status"][:1]),
        )

        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("source_count_mismatch", out)

    def test_machine_filter_suppresses_the_source_count_cross_check(self) -> None:
        """`/api/health` 不吃过滤条件，带过滤时数量本来就会对不上，不能报成异常。"""
        directory = self._scenario(
            HEALTHY,
            lambda payload: (
                payload.__setitem__("source_status", payload["source_status"][:1]),
                payload["summary"].__setitem__("machine", "linux-dev"),
            ),
        )

        code, out, _ = run_cli([
            "verify-cloud", "health", "--fixture-dir", directory, "--machine", "linux-dev",
        ])

        self.assertEqual(code, 0)
        self.assertNotIn("source_count_mismatch", out)


class TestVerifyCloudParity(unittest.TestCase):
    maxDiff = None

    def test_consistent_endpoints_exit_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("核对通过", out)

    def test_version_fields_absent_from_mobile_are_not_reported_as_a_difference(self) -> None:
        """`/api/mobile/summary` 刻意不带版本字段，这是设计，不是口径不一致。"""
        summary = json.loads((HEALTHY / "summary.json").read_text(encoding="utf-8"))
        mobile = json.loads((HEALTHY / "mobile_summary.json").read_text(encoding="utf-8"))
        self.assertIn("version_health", summary)
        self.assertTrue(all("version" in row for row in summary["source_status"]))
        self.assertNotIn("version_health", mobile)
        self.assertTrue(all("version" not in row for row in mobile["sources"]))

        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["differences"], [])
        self.assertIn(
            "source_status[].version",
            [row["field"] for row in report["known_differences"]],
        )

    def test_inconsistent_endpoints_exit_non_zero_and_list_every_differing_field(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(PARITY_MISMATCH), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 4)
        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(
            sorted(row["field"] for row in report["differences"]),
            [
                "period.total_tokens",
                "provider_slots[claude].quota.reason",
                "provider_slots[claude].quota.status",
                "provider_slots[claude].quota.window_count",
                "provider_slots[codex].usage.total_tokens",
                "provider_usage_coverage.attributed_tokens",
            ],
        )
        by_field = {row["field"]: row for row in report["differences"]}
        self.assertEqual(by_field["period.total_tokens"]["summary"], 900000)
        self.assertEqual(by_field["period.total_tokens"]["mobile"], 880000)

    def test_human_output_shows_both_sides_of_every_difference(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(PARITY_MISMATCH)])

        self.assertEqual(code, 4)
        self.assertIn("period.total_tokens", out)
        self.assertIn("900000", out)
        self.assertIn("880000", out)
        self.assertIn("provider_slots[codex].usage.total_tokens", out)
        self.assertIn("provider_slots[claude].quota.status", out)
        self.assertNotIn("核对通过", out)

    def test_compared_field_set_is_pinned(self) -> None:
        _, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        expected = [
            "period.account",
            "period.date",
            "period.end_date",
            "period.id",
            "period.input_tokens",
            "period.machine",
            "period.output_tokens",
            "period.start_date",
            "period.total_tokens",
            "provider_usage_coverage.attributed_tokens",
            "provider_usage_coverage.other_provider_tokens",
            "provider_usage_coverage.status",
            "provider_usage_coverage.total_tokens",
            "provider_usage_coverage.unattributed_tokens",
        ]
        for provider in ("claude", "codex", "antigravity"):
            for leaf in (
                "quota.last_verified_at",
                "quota.reason",
                "quota.source_id",
                "quota.source_type",
                "quota.status",
                "quota.window_count",
                "usage.cache_tokens",
                "usage.input_tokens",
                "usage.output_tokens",
                "usage.status",
                "usage.total_tokens",
            ):
                expected.append(f"provider_slots[{provider}].{leaf}")
        self.assertEqual(report["compared_fields"], sorted(expected))


SECRET = "sk-verify-cloud-should-never-print-this"


class TestVerifyCloudReadOnlyAccess(unittest.TestCase):
    """凭据只从环境变量读、只进请求头；能触达的端点只有只读 `/api/*`。"""

    def _args(self, **overrides):
        base = {
            "base_url": "https://usage.example.com",
            "token_env": "AI_USAGE_TEST_READ_TOKEN",
            "fixture_dir": None,
            "timeout": 15.0,
            "date": None,
            "period": None,
            "machine": None,
            "account": None,
            "as_json": False,
            "verify_command": "summary",
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_only_read_only_api_paths_are_reachable(self) -> None:
        self.assertEqual(
            sorted(verify_cloud.READ_ONLY_PATHS.values()),
            ["/api/health", "/api/mobile/summary", "/api/summary"],
        )
        for path in verify_cloud.READ_ONLY_PATHS.values():
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/"))

    def test_exit_codes_are_named_constants_with_distinct_values(self) -> None:
        codes = {
            "EXIT_OK": verify_cloud.EXIT_OK,
            "EXIT_DATA_ISSUE": verify_cloud.EXIT_DATA_ISSUE,
            "EXIT_PARITY_MISMATCH": verify_cloud.EXIT_PARITY_MISMATCH,
            "EXIT_FETCH_FAILED": verify_cloud.EXIT_FETCH_FAILED,
        }
        self.assertEqual(verify_cloud.EXIT_OK, 0)
        self.assertEqual(len(set(codes.values())), len(codes))
        self.assertTrue(all(value != 0 for name, value in codes.items() if name != "EXIT_OK"))

    def test_request_is_read_only_and_carries_the_token_only_in_the_header(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_READ_TOKEN": SECRET}, clear=False):
            source = verify_cloud.build_read_source(self._args())
        request = source.build_request(
            verify_cloud.ENDPOINT_SUMMARY,
            {"period": "today", "date": "2026-06-03", "machine": None, "account": None},
        )

        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.full_url,
            "https://usage.example.com/api/summary?date=2026-06-03&period=today",
        )
        self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET}")
        self.assertNotIn(SECRET, request.full_url)
        self.assertNotIn(SECRET, source.label)

    def test_base_url_label_drops_path_and_query(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_READ_TOKEN": SECRET}, clear=False):
            source = verify_cloud.build_read_source(
                self._args(base_url=f"https://usage.example.com/base?t={SECRET}")
            )

        self.assertNotIn(SECRET, source.label)
        self.assertEqual(source.label, "https://usage.example.com")

    def test_userinfo_in_base_url_is_refused_outright_not_merely_hidden_from_the_label(self) -> None:
        """只把 userinfo 从 label 里抹掉是不够的。

        真正的泄露发生在 urlopen 阶段：CPython 抛 InvalidURL，异常信息里带密码原文，
        而它继承自 HTTPException，既不是 HTTPError 也不是 URLError，read() 的两个
        except 都捕不到，密码随 traceback 打到 stderr。所以要在入口就拒绝。
        """
        with unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_READ_TOKEN": SECRET}, clear=False):
            code, out, err = run_cli([
                "verify-cloud", "summary",
                "--base-url", f"https://user:{SECRET}@usage.example.com",
                "--token-env", "AI_USAGE_TEST_READ_TOKEN",
            ])

        self.assertEqual(code, verify_cloud.EXIT_FETCH_FAILED)
        self.assertNotIn(SECRET, out)
        self.assertNotIn(SECRET, err)
        self.assertNotIn("Traceback", err)

    def test_missing_token_env_exits_fetch_failed_and_names_only_the_variable(self) -> None:
        env = dict(os.environ)
        env.pop("AI_USAGE_TEST_READ_TOKEN", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            code, out, err = run_cli([
                "verify-cloud", "summary",
                "--base-url", "https://usage.example.com",
                "--token-env", "AI_USAGE_TEST_READ_TOKEN",
            ])

        self.assertEqual(code, 5)
        self.assertIn("AI_USAGE_TEST_READ_TOKEN", err)
        self.assertEqual(out, "")

    def test_neither_source_selected_exits_fetch_failed(self) -> None:
        code, _, err = run_cli(["verify-cloud", "summary"])

        self.assertEqual(code, 5)
        self.assertIn("--fixture-dir", err)

    def test_missing_fixture_file_exits_fetch_failed(self) -> None:
        directory = tempfile.mkdtemp(prefix="verify-cloud-empty-")
        self.addCleanup(shutil.rmtree, directory, True)

        code, _, err = run_cli(["verify-cloud", "summary", "--fixture-dir", directory])

        self.assertEqual(code, 5)
        self.assertIn("summary.json", err)

    def test_unusable_base_url_exits_fetch_failed_instead_of_crashing(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_READ_TOKEN": SECRET}, clear=False):
            code, _, err = run_cli([
                "verify-cloud", "summary",
                "--base-url", "not-a-url",
                "--token-env", "AI_USAGE_TEST_READ_TOKEN",
            ])

        self.assertEqual(code, 5)
        self.assertNotIn(SECRET, err)
        self.assertNotIn("Traceback", err)


class TestVerifyCloudOutputCarriesNoSecrets(unittest.TestCase):
    """核对输出不得含凭据、auth 路径或原始用量日志内容。"""

    FORBIDDEN = (
        SECRET,
        "Bearer",
        "Authorization",
        "auth.json",
        ".credentials.json",
        "/home/",
        "/Users/",
        "/.claude",
        "/.codex",
        "eyJ",
    )

    def test_the_http_path_that_actually_carries_the_token_never_echoes_it(self) -> None:
        """真正会接触凭据的是 HTTP 路径，fixture 路径压根不读环境变量。

        `build_read_source` 在 `--fixture-dir` 分支就 return 了，`os.environ` 从未被读到，
        所以只用 fixture 跑出来的「无凭据泄露」是空证明。这条用例走 HttpReadSource
        自己的构造与异常路径，让守卫真的覆盖凭据所在的那一条路。
        """
        source = verify_cloud.HttpReadSource(
            "https://usage.example.invalid", SECRET, timeout=1.0
        )

        request = source.build_request(verify_cloud.ENDPOINT_SUMMARY, {"period": "today"})
        self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET}")
        self.assertNotIn(SECRET, request.full_url)
        self.assertNotIn(SECRET, source.label)

        def _boom(*_args, **_kwargs):
            raise OSError(f"connect failed for {SECRET}")

        with unittest.mock.patch.object(verify_cloud.urlrequest, "urlopen", _boom):
            with self.assertRaises(verify_cloud.ReadSourceError) as caught:
                source.read(verify_cloud.ENDPOINT_SUMMARY, {})
        self.assertNotIn(SECRET, str(caught.exception))

    def test_userinfo_base_url_is_refused_before_any_request_is_built(self) -> None:
        with self.assertRaises(verify_cloud.ReadSourceError) as caught:
            verify_cloud.HttpReadSource("https://u:pw-secret@host.invalid", SECRET)
        self.assertNotIn("pw-secret", str(caught.exception))

    def test_no_subcommand_output_contains_credentials_or_raw_paths(self) -> None:
        env = {
            "AI_USAGE_READ_TOKEN": SECRET,
            "AI_USAGE_INGEST_TOKEN": SECRET,
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            for scenario in (HEALTHY, DEGRADED, PARITY_MISMATCH):
                for command in ("summary", "limits", "health", "parity"):
                    for extra in ([], ["--json"]):
                        with self.subTest(scenario=scenario.name, command=command, extra=extra):
                            _, out, err = run_cli([
                                "verify-cloud", command, "--fixture-dir", str(scenario), *extra,
                            ])
                            for forbidden in self.FORBIDDEN:
                                self.assertNotIn(forbidden, out)
                                self.assertNotIn(forbidden, err)


class TestVerifyCloudFixtureScenarioCoverage(unittest.TestCase):
    """fixture 的场景覆盖度断言（纯结构，不耦合读模型）。

    「fixture 必须由 owner 现算对齐」的守卫已随 #74 迁到 Worker 侧
    `cloudflare/native-worker/test/verify-cloud-fixtures.test.ts`（块 8 接替）：
    mobile DTO 对 `buildMobileSummary`、版本块对 `buildVersionHealth`、
    负面 fixture 的有效性各有断言，改这批 fixture 会触发 Worker 测试
    （scripts/verify.sh 的触发判据含 tests/fixtures/verify_cloud/ 前缀）。
    """

    maxDiff = None

    def _load(self, scenario: Path, name: str):
        return json.loads((scenario / name).read_text(encoding="utf-8"))

    def test_degraded_fixture_really_covers_all_four_limit_trust_states(self) -> None:
        summary = self._load(DEGRADED, "summary.json")
        states = {
            (row["official"], row["confidence"], row["status"])
            for row in summary["limits"]
        }
        self.assertIn((True, "observed", "ok"), states)
        self.assertIn((False, "estimated", "ok"), states)
        self.assertIn((False, "missing", "provider_failed"), states)
        self.assertIn((False, "unknown", "unsupported"), states)


class TestVerifyCloudJsonSchema(unittest.TestCase):
    """`--json` 是给机器判定用的，字段集合必须钉死：增、删、改名都要红。

    只断言「某几个键存在」挡不住字段悄悄增加，下游按旧结构解析就会漏掉新状态。
    """

    maxDiff = None

    def _report(self, command: str, scenario: Path) -> dict:
        code, out, _ = run_cli(["verify-cloud", command, "--fixture-dir", str(scenario), "--json"])
        self.assertIn(code, (0, 3, 4))
        return json.loads(out)

    def test_summary_json_schema_is_pinned(self) -> None:
        report = self._report("summary", DEGRADED)

        self.assertEqual(sorted(report), [
            "command", "coverage", "exit_code", "generated_at", "issues", "period",
            "provider_slots", "requested", "source", "status", "timezone", "totals",
        ])
        self.assertEqual(sorted(report["period"]), [
            "account", "date", "end_date", "id", "machine", "start_date",
        ])
        self.assertEqual(sorted(report["totals"]), [
            "cache_creation_tokens", "cache_read_tokens", "input_tokens",
            "output_tokens", "total_tokens",
        ])
        self.assertEqual(sorted(report["coverage"]), [
            "attributed_tokens", "other_provider_tokens", "status",
            "total_tokens", "unattributed_tokens",
        ])
        self.assertEqual(sorted(report["requested"]), ["account", "date", "machine", "period"])
        for row in report["provider_slots"]:
            self.assertEqual(sorted(row), [
                "cache_tokens", "input_tokens", "output_tokens", "provider",
                "quota_last_verified_at", "quota_reason", "quota_source_id",
                "quota_source_type", "quota_status", "quota_window_count",
                "total_tokens", "usage_status",
            ])
        for row in report["issues"]:
            self.assertEqual(sorted(row), ["code", "detail"])

    def test_limits_json_schema_is_pinned(self) -> None:
        report = self._report("limits", DEGRADED)

        self.assertEqual(sorted(report), [
            "command", "degraded_count", "exit_code", "generated_at", "issues",
            "provider_quota", "requested", "source", "status", "timezone",
            "trusted_count", "windows",
        ])
        for row in report["windows"]:
            self.assertEqual(sorted(row), [
                "confidence", "degrade_reasons", "observed_at", "official", "provider",
                "remaining_percent", "reset_at", "source_id", "source_type", "status",
                "trust", "used_percent", "window", "window_duration_minutes",
            ])
        for row in report["provider_quota"]:
            self.assertEqual(sorted(row), [
                "last_verified_at", "provider", "reason", "source_id",
                "source_type", "status", "window_count",
            ])

    def test_health_json_schema_is_pinned(self) -> None:
        report = self._report("health", DEGRADED)

        self.assertEqual(sorted(report), [
            "backend_mode", "canonical_store", "command", "exit_code", "generated_at",
            "issues", "limits_health", "requested", "snapshot_updated_at", "source",
            "source_total", "sources", "status", "status_counts", "version_counts",
        ])
        self.assertEqual(sorted(report["limits_health"]), [
            "effective_window_count", "latest_observed_at",
            "raw_window_count", "stale_window_count",
        ])
        for row in report["sources"]:
            self.assertEqual(sorted(row), [
                "accuracy_status", "collector_version", "coverage", "display_name",
                "last_observed_at", "machine", "os_user", "platform", "source_id",
                "status", "version_state",
            ])
            for item in row["coverage"]:
                self.assertEqual(sorted(item), ["agent", "end", "start", "status"])

    def test_parity_json_schema_is_pinned(self) -> None:
        report = self._report("parity", PARITY_MISMATCH)

        self.assertEqual(sorted(report), [
            "command", "compared_fields", "differences", "exit_code", "issues",
            "known_differences", "mobile_generated_at", "requested", "source",
            "status", "summary_generated_at",
        ])
        for row in report["differences"]:
            self.assertEqual(sorted(row), ["field", "mobile", "summary"])
        for row in report["known_differences"]:
            self.assertEqual(sorted(row), ["field", "reason"])

    def test_every_command_reports_its_own_exit_code_inside_the_json(self) -> None:
        expected = {
            (str(HEALTHY), "summary"): 0,
            (str(HEALTHY), "limits"): 0,
            (str(HEALTHY), "health"): 0,
            (str(HEALTHY), "parity"): 0,
            (str(DEGRADED), "summary"): 3,
            (str(DEGRADED), "limits"): 3,
            (str(DEGRADED), "health"): 3,
            (str(PARITY_MISMATCH), "parity"): 4,
        }
        for (scenario, command), code in expected.items():
            with self.subTest(scenario=Path(scenario).name, command=command):
                actual, out, _ = run_cli([
                    "verify-cloud", command, "--fixture-dir", scenario, "--json",
                ])
                self.assertEqual(actual, code)
                self.assertEqual(json.loads(out)["exit_code"], code)


if __name__ == "__main__":
    unittest.main()


class TestVerifyCloudParityStructuralFloor(unittest.TestCase):
    """parity 必须有结构下限。

    两个端点由同一个 Worker 提供，共享失败模式（200 + 错误信封、CDN 缓存了空对象、
    read model 抛错后返回兜底空快照）时会同时退化成同形状的垃圾。逐字段比对此时
    两边都取到 None，None == None，parity 会报「核对通过」——而 README 把它写成
    可以直接进 CI 的门禁。这是最难被发现的假绿：它长得像核对结果。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="verify-cloud-floor-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, payload: dict) -> str:
        for name in ("summary", "mobile_summary", "health"):
            (Path(self.tmp) / f"{name}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        return self.tmp

    def test_two_empty_documents_are_a_data_issue_not_a_pass(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", self._write({})])

        self.assertEqual(code, verify_cloud.EXIT_DATA_ISSUE)
        self.assertNotIn("核对通过", out)

    def test_period_without_totals_is_a_data_issue(self) -> None:
        payload = {"period": {"id": "today", "start_date": "2026-06-03", "end_date": "2026-06-03"}}
        code, _, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", self._write(payload)])

        self.assertEqual(code, verify_cloud.EXIT_DATA_ISSUE)

    def test_the_floor_names_the_missing_block_in_json(self) -> None:
        code, out, _ = run_cli(
            ["verify-cloud", "parity", "--fixture-dir", self._write({}), "--json"]
        )
        report = json.loads(out)

        self.assertEqual(code, verify_cloud.EXIT_DATA_ISSUE)
        self.assertEqual(report["exit_code"], verify_cloud.EXIT_DATA_ISSUE)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("parity_input_unusable", codes)


class TestVerifyCloudHttpFailuresNeverLeakOrCrash(unittest.TestCase):
    """取数异常必须归一到 EXIT_FETCH_FAILED，且绝不回显 URL 里的凭据。

    `--base-url` 里带 userinfo 时，CPython 在 urlopen 阶段抛 InvalidURL，
    它是 HTTPException/ValueError 的子类，既不是 HTTPError 也不是 URLError，
    现有的两个 except 都捕不到——密码原文会随 traceback 打到 stderr。
    """

    def test_userinfo_in_base_url_is_rejected_without_echoing_the_password(self) -> None:
        password = "sk-my-secret-pass"
        with unittest.mock.patch.dict(
            os.environ, {"AI_USAGE_READ_TOKEN": SECRET}, clear=False
        ):
            code, out, err = run_cli([
                "verify-cloud", "summary",
                "--base-url", f"https://user:{password}@usage.example.invalid",
            ])

        self.assertEqual(code, verify_cloud.EXIT_FETCH_FAILED)
        self.assertNotIn(password, out)
        self.assertNotIn(password, err)
        self.assertNotIn("Traceback", err)

    def test_non_utf8_response_body_exits_fetch_failed(self) -> None:
        source = verify_cloud.HttpReadSource(
            "https://usage.example.invalid", SECRET, timeout=1.0
        )

        class _Body:
            def read(self):
                return b"\xff\xfe\x00bad"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with unittest.mock.patch.object(verify_cloud.urlrequest, "urlopen", lambda *a, **k: _Body()):
            with self.assertRaises(verify_cloud.ReadSourceError) as caught:
                source.read(verify_cloud.ENDPOINT_SUMMARY, {})

        self.assertNotIn(SECRET, str(caught.exception))

    def test_socket_timeout_while_reading_body_exits_fetch_failed(self) -> None:
        source = verify_cloud.HttpReadSource(
            "https://usage.example.invalid", SECRET, timeout=1.0
        )

        def _boom(*_args, **_kwargs):
            raise TimeoutError("timed out")

        with unittest.mock.patch.object(verify_cloud.urlrequest, "urlopen", _boom):
            with self.assertRaises(verify_cloud.ReadSourceError) as caught:
                source.read(verify_cloud.ENDPOINT_SUMMARY, {})

        self.assertNotIn(SECRET, str(caught.exception))


class TestVerifyCloudNamesUncheckableDimensions(unittest.TestCase):
    """后端没有版本读取侧时，不能报「核对通过」。

    写这组用例时（#60），生产 Worker 还不返回 `source_status[].version` 与
    `/api/health` 的 `versions`；该缺口后来已由 #63 交付、#81 部署回读闭合。
    但这组行为仍然必要：任何后端（旧版本、降级形态、其他部署）缺这两个维度时，
    verify-cloud 若判 exit 0，就是把缺口翻译成绿灯——无图形界面的用户拿到
    「核对通过」，而「哪台设备还在跑旧采集器」——#58 存在的唯一理由——
    从头到尾没被核对过。

    未核对不等于核对通过。缺维度必须说出来。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="verify-cloud-noversion-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("summary", "mobile_summary", "health"):
            src = json.loads((HEALTHY / f"{name}.json").read_text(encoding="utf-8"))
            src.pop("version_health", None)
            src.pop("versions", None)
            entries = src.get("source_status")
            if isinstance(entries, dict):
                entries = entries.get("non_ok") or []
            for entry in entries or []:
                if isinstance(entry, dict):
                    entry.pop("version", None)
            (Path(self.tmp) / f"{name}.json").write_text(json.dumps(src), encoding="utf-8")

    def test_health_without_any_version_block_is_not_reported_as_a_pass(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", self.tmp])

        self.assertNotEqual(code, verify_cloud.EXIT_OK)
        self.assertNotIn("核对通过", out)

    def test_the_uncheckable_version_dimension_is_named_in_json(self) -> None:
        code, out, _ = run_cli(
            ["verify-cloud", "health", "--fixture-dir", self.tmp, "--json"]
        )
        report = json.loads(out)

        self.assertEqual(code, report["exit_code"])
        self.assertIn("version_block_unavailable", {i["code"] for i in report["issues"]})

    def test_a_backend_that_does_carry_versions_stays_clean(self) -> None:
        code, _, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, verify_cloud.EXIT_OK)
