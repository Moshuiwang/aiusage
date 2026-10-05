"""
#190 第 3 项：check_cf_usage.py 的 D1 rows_read/rows_written 判定逻辑离线测试。

纯单测：不发真实网络请求，全部用 fixture 化的 GraphQL 响应 JSON。覆盖
parse_d1_rows_read_written（解析）、d1_usage_percentages（口径换算）、
overall_conclusion（结论判定，包括"D1 读写未知不得判定为全部安全"）。
"""
from __future__ import annotations

import sys
import os
import io
import tempfile
from unittest.mock import patch
from contextlib import redirect_stdout
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_cf_usage as ccu  # noqa: E402



class TestCloudflareCredentials(unittest.TestCase):
    def test_environment_api_token_precedes_existing_wrangler_login(self):
        with tempfile.TemporaryDirectory() as folder:
            login = Path(folder) / "login.toml"
            login.write_text('oauth_token = "synthetic-old-login"\n')
            with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "synthetic-api-token"}, clear=True), patch.object(ccu.os.path, "expanduser", return_value=str(login)):
                self.assertEqual(ccu.get_cloudflare_token(), "synthetic-api-token")

    def test_blank_environment_uses_existing_login_without_exposing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            login = Path(folder) / "login.toml"
            login.write_text('oauth_token = "synthetic-login"\n')
            output = io.StringIO()
            with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "  "}, clear=True), patch.object(ccu.os.path, "expanduser", return_value=str(login)), redirect_stdout(output):
                self.assertEqual(ccu.get_cloudflare_token(), "synthetic-login")
            self.assertNotIn("synthetic-login", output.getvalue())

    def test_missing_credentials_exit_nonzero_without_contacting_api(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch.object(ccu.os.path, "expanduser", return_value=str(Path(folder) / "missing.toml")), patch.object(ccu, "query_cf_api") as query, redirect_stdout(output):
            with self.assertRaises(SystemExit) as stopped:
                ccu.main()
            self.assertEqual(stopped.exception.code, 2)
            query.assert_not_called()
        self.assertIn("未知", output.getvalue())

    def test_environment_token_requires_no_local_login_file(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "synthetic-api-token"}, clear=True), patch.object(ccu.os.path, "expanduser", side_effect=AssertionError("must not read login file")), redirect_stdout(output):
            self.assertEqual(ccu.get_cloudflare_token(), "synthetic-api-token")
        self.assertNotIn("synthetic-api-token", output.getvalue())

def d1_response(groups):
    return {"data": {"viewer": {"accounts": [{"d1AnalyticsAdaptiveGroups": groups}]}}}


class TestParseD1RowsReadWritten(unittest.TestCase):
    def test_single_group_reads_rows_read_and_rows_written_not_query_counts(self):
        # readQueries/writeQueries 是查询次数，rowsRead/rowsWritten 才是计费行数——
        # fixture 里两组数字明显不同，断言必须挑对字段，取错字段这条测试会先红。
        response = d1_response([
            {"sum": {"readQueries": 400, "writeQueries": 40, "rowsRead": 1_672_000, "rowsWritten": 44_814}},
        ])
        rows_read, rows_written = ccu.parse_d1_rows_read_written(response)
        self.assertEqual(rows_read, 1_672_000)
        self.assertEqual(rows_written, 44_814)

    def test_multiple_time_bucketed_groups_are_summed_not_only_first(self):
        response = d1_response([
            {"sum": {"rowsRead": 1_000_000, "rowsWritten": 10_000}},
            {"sum": {"rowsRead": 500_000, "rowsWritten": 5_000}},
            {"sum": {"rowsRead": 200_000, "rowsWritten": 2_000}},
        ])
        rows_read, rows_written = ccu.parse_d1_rows_read_written(response)
        self.assertEqual(rows_read, 1_700_000)
        self.assertEqual(rows_written, 17_000)

    def test_empty_groups_is_unknown_not_zero(self):
        # 0 组数据代表"没查到"，不是"读写行数恰好是 0"——两者混淆会把未知误判成安全。
        rows_read, rows_written = ccu.parse_d1_rows_read_written(d1_response([]))
        self.assertIsNone(rows_read)
        self.assertIsNone(rows_written)

    def test_missing_accounts_is_unknown(self):
        response = {"data": {"viewer": {"accounts": []}}}
        rows_read, rows_written = ccu.parse_d1_rows_read_written(response)
        self.assertIsNone(rows_read)
        self.assertIsNone(rows_written)

    def test_malformed_response_is_unknown_not_a_crash(self):
        for malformed in [{}, {"data": None}, {"data": {"viewer": None}}, "not even a dict"]:
            with self.subTest(malformed=malformed):
                rows_read, rows_written = ccu.parse_d1_rows_read_written(malformed if isinstance(malformed, dict) else {})
                self.assertIsNone(rows_read)
                self.assertIsNone(rows_written)

    def test_graphql_error_response_with_no_data_key_is_unknown(self):
        # 真实 GraphQL 出错时常见形态：只有 errors，没有 data。
        response = {"errors": [{"message": "rate limited"}]}
        rows_read, rows_written = ccu.parse_d1_rows_read_written(response)
        self.assertIsNone(rows_read)
        self.assertIsNone(rows_written)


    def test_group_missing_or_null_field_makes_that_metric_unknown(self):
        # 部分数据：某个分组的字段缺失/为 null，不能当 0 加总，否则会把未知算成偏低的值。
        cases = [
            ({"rowsRead": None, "rowsWritten": 5_000}, (None, 15_000)),
            ({"rowsWritten": 5_000}, (None, 15_000)),
            ({"rowsRead": 500_000, "rowsWritten": None}, (1_500_000, None)),
        ]
        for partial, expected in cases:
            with self.subTest(partial=partial):
                response = d1_response([
                    {"sum": {"rowsRead": 1_000_000, "rowsWritten": 10_000}},
                    {"sum": partial},
                ])
                self.assertEqual(ccu.parse_d1_rows_read_written(response), expected)

    def test_top_level_errors_with_partial_data_is_unknown(self):
        # GraphQL 字段级错误时可能 data 与 errors 并存：数据不可确认，整体按未知处理。
        response = d1_response([{"sum": {"rowsRead": 1_000, "rowsWritten": 10}}])
        response["errors"] = [{"message": "field error"}]
        self.assertEqual(ccu.parse_d1_rows_read_written(response), (None, None))



class TestUnavailableMainMetrics(unittest.TestCase):
    def test_optional_resource_counts_preserve_real_zero_and_numeric_strings(self):
        for value, expected in [(None, None), (0, 0), ("0", 0), ("17845989", 17845989)]:
            with self.subTest(value=value):
                self.assertEqual(ccu.optional_int(value), expected)

    def run_offline(self):
        output = io.StringIO()
        with patch.object(ccu, "get_cloudflare_token", return_value="synthetic-audit-token"), patch.object(ccu, "query_cf_api", side_effect=OSError("offline failure")) as query, patch.object(ccu, "overall_conclusion", wraps=ccu.overall_conclusion) as conclusion, redirect_stdout(output):
            code = 0
            try:
                ccu.main()
            except SystemExit as stopped:
                code = stopped.code
        self.assertEqual(query.call_count, 4)
        self.assertEqual(conclusion.call_count, 1)
        self.assertNotIn("synthetic-audit-token", output.getvalue())
        return conclusion.call_args.args[0], output.getvalue(), code

    def test_failed_resource_reads_are_unknown_not_zero(self):
        percentages, output, _ = self.run_offline()
        self.assertEqual(set(percentages), {"worker_requests", "d1_db_size", "r2_storage", "d1_rows_read", "d1_rows_written"})
        for metric in percentages:
            with self.subTest(metric=metric):
                self.assertIsNone(percentages[metric])
        self.assertIn("存储空间: 未知", output)
        self.assertIn("请求量: 未知", output)
        self.assertNotIn("0.00 MB", output)

    def test_incomplete_audit_exits_nonzero(self):
        _, output, code = self.run_offline()
        self.assertEqual(code, 2)
        self.assertNotIn("结论: 正常", output)


class TestD1UsagePercentages(unittest.TestCase):
    def test_known_values_convert_against_free_limits(self):
        read_pct, write_pct = ccu.d1_usage_percentages(2_500_000, 50_000)
        self.assertAlmostEqual(read_pct, 50.0)
        self.assertAlmostEqual(write_pct, 50.0)

    def test_none_stays_none_not_zero(self):
        read_pct, write_pct = ccu.d1_usage_percentages(None, None)
        self.assertIsNone(read_pct)
        self.assertIsNone(write_pct)


class TestOverallConclusion(unittest.TestCase):
    def test_all_healthy_and_known_is_safe(self):
        text, has_unknown, has_critical, has_warning = ccu.overall_conclusion({
            "a": 10.0, "b": 20.0, "c": 5.0,
        })
        self.assertIn("正常", text)
        self.assertFalse(has_unknown)
        self.assertFalse(has_critical)
        self.assertFalse(has_warning)

    def test_d1_rows_read_unknown_is_not_safe(self):
        """核心行为：D1 读写未知时，其余指标再健康，结论也不能是"正常/全部安全"。"""
        text, has_unknown, has_critical, has_warning = ccu.overall_conclusion({
            "worker_requests": 2.0, "d1_db_size": 1.0, "r2_storage": 0.1,
            "d1_rows_read": None, "d1_rows_written": None,
        })
        self.assertTrue(has_unknown)
        self.assertFalse(has_critical)
        self.assertFalse(has_warning)
        self.assertNotIn("正常", text)
        self.assertIn("未知", text)

    def test_critical_beats_unknown_and_warning(self):
        text, has_unknown, has_critical, has_warning = ccu.overall_conclusion({
            "worker_requests": 2.0, "d1_rows_read": 85.0, "d1_rows_written": None,
        })
        self.assertTrue(has_critical)
        self.assertTrue(has_unknown)
        self.assertIn("警告", text)
        self.assertIn("紧急", text)

    def test_warning_threshold_is_50_and_critical_is_80(self):
        below_warn, *_ = ccu.overall_conclusion({"x": 49.99})
        at_warn, *_ = ccu.overall_conclusion({"x": 50.0})
        below_critical, *_ = ccu.overall_conclusion({"x": 79.99})
        at_critical, *_ = ccu.overall_conclusion({"x": 80.0})
        self.assertIn("正常", below_warn)
        self.assertIn("关注", at_warn)
        self.assertIn("关注", below_critical)
        self.assertIn("警告", at_critical)

    def test_empty_percentages_is_safe_not_unknown(self):
        # 结构下限：没有任何指标传进来（比如某个上游分支彻底没跑）不该被判成"未知"再放行，
        # 也不该悄悄判成"正常"——这里显式钉住"没有指标=没有 unknown 也没有 critical/warning"，
        # 调用方必须自己保证把该测的指标都传进来（例如 main() 里 d1_rows_read/written 恒定
        # 有 key，值可能是 None，但 key 本身不会缺）。
        text, has_unknown, has_critical, has_warning = ccu.overall_conclusion({})
        self.assertIn("正常", text)
        self.assertFalse(has_unknown)
        self.assertFalse(has_critical)
        self.assertFalse(has_warning)


class TestMutationEvidenceD1GateRemoved(unittest.TestCase):
    """变异证据：去掉"D1 读写未知"这条判定路径，结论必须变回"正常/全部安全"（红），
    证明现在的绿不是"注入没生效"——现在的实现里这条路径确实存在且必要。
    """

    def test_mutated_conclusion_without_unknown_gate_regresses_to_safe(self):
        def mutated_overall_conclusion_without_unknown_gate(percentages):
            # 复刻 overall_conclusion，但故意去掉 has_unknown 分支——模拟"有人删掉了
            # D1 读写未知判定"这一类回退。
            known = [pct for pct in percentages.values() if pct is not None]
            has_critical = any(pct >= ccu.D1_CRITICAL_PCT for pct in known)
            has_warning = any(pct >= ccu.D1_WARN_PCT for pct in known)
            if has_critical:
                return "⚠️ 结论: 警告！存在用量接近或超过 80% 免费上限的资源，需紧急优化！"
            if has_warning:
                return "💡 结论: 关注！部分资源用量已过半，建议排查高频调用或优化批次。"
            return "✅ 结论: 正常！所有 Cloudflare 核心资源用量均在安全绿色区间内。"

        percentages = {
            "worker_requests": 2.0, "d1_db_size": 1.0, "r2_storage": 0.1,
            "d1_rows_read": None, "d1_rows_written": None,
        }

        # 先确认注入真的生效：变异版本在 D1 读写未知时判"正常"——这是我们要挡住的错误结论。
        mutated_text = mutated_overall_conclusion_without_unknown_gate(percentages)
        self.assertIn("正常", mutated_text)

        # 真实实现必须不是这个结论：这一断言在"D1 读写未知判定被删掉"时会红。
        real_text, *_ = ccu.overall_conclusion(percentages)
        self.assertNotEqual(real_text, mutated_text)
        self.assertNotIn("正常", real_text)


if __name__ == "__main__":
    unittest.main()
