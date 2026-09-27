"""#183-a：`scripts/export_calibration_fixture.py` 的转换逻辑单测。

这个脚本是 `cloudflare/native-worker/test/calibration_fixture.json` 的 owner——fixture 本身
不许手写（AGENTS.md）。但脚本的**真实输入**是一次性对生产 D1 的只读导出（wrangler
`--remote --json`），这台开发机没有那次导出留下的原始文件，也没有 Cloudflare 凭据去重新拉一份
（`.claude/rules/cloudflare.md`：真实 Cloudflare 账号操作只能在 macOS 侧 Ops Agent 执行）。
所以这里做不到「重新导出真实数据再逐字节 diff」那种防陈旧测试。

能做、也必须做的是：**脚本的转换逻辑本身**（脱敏、模型族映射、unattributed 完整性补齐）
用可离线重放的合成输入独立验证——这是 fixture 生成逻辑唯一的正确性保证，`calibration_fixture.json`
本身的可信度完全依赖这几个函数不出错。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_calibration_fixture import (  # noqa: E402
    anonymize_source_ids,
    build_hourly_family_facts,
    build_limit_observations,
    family_for_model,
)


class FamilyForModelTest(unittest.TestCase):
    def test_claude_families(self):
        self.assertEqual(family_for_model("claude", "claude-opus-4-8"), "opus")
        self.assertEqual(family_for_model("claude", "claude-sonnet-5"), "sonnet")
        self.assertEqual(family_for_model("claude", "claude-haiku-4-5-20251001"), "haiku")
        self.assertEqual(family_for_model("claude", "claude-fable-5-1"), "fable")

    def test_non_anthropic_model_under_claude_agent_is_unmapped(self):
        self.assertIsNone(family_for_model("claude", "deepseek-v4-pro"))

    def test_codex_families_review_before_version_prefix(self):
        self.assertEqual(family_for_model("codex", "codex-auto-review"), "review")
        self.assertEqual(family_for_model("codex", "gpt-6-astra"), "gpt-6")
        self.assertEqual(family_for_model("codex", "gpt-5.6-luna"), "gpt-5.6")

    def test_antigravity_families_and_unknown_model_name(self):
        self.assertEqual(family_for_model("antigravity", "gemini-3.8-flash-tiered"), "flash")
        self.assertEqual(family_for_model("antigravity", "gemini-pro-default"), "pro")
        self.assertEqual(family_for_model("antigravity", "claude-opus-4-6-thinking"), "claude-on-antigravity")
        self.assertIsNone(family_for_model("antigravity", "unknown"))


class AnonymizeSourceIdsTest(unittest.TestCase):
    def test_stable_mapping_by_first_appearance_no_pii_leaks_through(self):
        lim_rows = [{"source_id": "mac-local"}, {"source_id": "linux-biai-wangzp"}]
        fact_rows = [{"source_id": "linux-biai-wangzp"}, {"source_id": "tz-wangzp"}]
        mapping = anonymize_source_ids(lim_rows, fact_rows)
        self.assertEqual(mapping["mac-local"], "source-a")
        self.assertEqual(mapping["linux-biai-wangzp"], "source-b")
        self.assertEqual(mapping["tz-wangzp"], "source-c")
        # 脱敏后的值不能包含任何原始机器名/用户名子串。
        for original, anonymized in mapping.items():
            self.assertNotIn("mac", anonymized)
            self.assertNotIn("wangzp", anonymized)
            self.assertNotIn("linux", anonymized)

    def test_build_limit_observations_drops_pii_fields_keeps_only_declared_shape(self):
        lim_rows = [{
            "source_id": "mac-local", "provider": "claude", "observed_at": "t0", "reset_at": "t1",
            "used_percent": 50, "window_duration_minutes": 10080,
            "confidence": "observed", "status": "ok", "recorded_at": "t2",
        }]
        mapping = {"mac-local": "source-a"}
        out = build_limit_observations(lim_rows, mapping)
        self.assertEqual(out, [{
            "source_id": "source-a", "provider": "claude", "observed_at": "t0", "reset_at": "t1",
            "used_percent": 50, "window_duration_minutes": 10080,
        }])
        # 结构下限：确认 PII 字段（confidence/status/recorded_at 本身不是 PII，但机器身份相关字段）
        # 没有原样带过去——只保留脚本声明的 6 个字段。
        self.assertEqual(set(out[0].keys()), {"source_id", "provider", "observed_at", "reset_at", "used_percent", "window_duration_minutes"})


class BuildHourlyFamilyFactsTest(unittest.TestCase):
    def test_fact_with_no_model_rows_goes_entirely_to_unattributed(self):
        fact_rows = [{
            "fact_id": "f1", "agent": "codex", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
            "input_tokens": 100, "output_tokens": 200, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }]
        out = build_hourly_family_facts(fact_rows, [])
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row["model_family"], "unattributed")
        self.assertEqual(row["input_tokens"], 100)
        self.assertEqual(row["output_tokens"], 200)

    def test_fact_with_partial_model_coverage_splits_matched_family_and_unattributed_shortfall(self):
        fact_rows = [{
            "fact_id": "f2", "agent": "claude", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
            "input_tokens": 0, "output_tokens": 1000, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }]
        # model 行合计只有 700，跟 fact 总量 1000 之间差 300 → unattributed。
        model_rows = [{"fact_id": "f2", "model": "claude-opus-4-8", "input_tokens": 0, "output_tokens": 700, "cache_creation_tokens": 0, "cache_read_tokens": 0}]
        out = build_hourly_family_facts(fact_rows, model_rows)
        by_family = {row["model_family"]: row for row in out}
        self.assertEqual(set(by_family.keys()), {"opus", "unattributed"})
        self.assertEqual(by_family["opus"]["output_tokens"], 700)
        self.assertEqual(by_family["unattributed"]["output_tokens"], 300)

    def test_model_row_present_but_unmapped_family_counts_toward_completeness_not_unattributed(self):
        # deepseek 有真实 model 行（不是缺失），但不属于任何已知 Claude 族——
        # 按脚本文档的定义，它计入 model 行合计（缩小 unattributed 差额），但不产出任何族的行。
        fact_rows = [{
            "fact_id": "f3", "agent": "claude", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
            "input_tokens": 0, "output_tokens": 1000, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }]
        model_rows = [{"fact_id": "f3", "model": "deepseek-v4-pro", "input_tokens": 0, "output_tokens": 1000, "cache_creation_tokens": 0, "cache_read_tokens": 0}]
        out = build_hourly_family_facts(fact_rows, model_rows)
        # model 行合计(1000) == fact 总量(1000)，差额为 0 → 不产出 unattributed 行；
        # deepseek 不映射到任何族 → 也不产出任何已知族的行。这个 fact 完全不出现在输出里。
        self.assertEqual(out, [])

    def test_multiple_facts_in_same_hour_and_family_are_summed(self):
        fact_rows = [
            {"fact_id": "f4", "agent": "claude", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
             "input_tokens": 0, "output_tokens": 500, "cache_creation_tokens": 0, "cache_read_tokens": 0},
            {"fact_id": "f5", "agent": "claude", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
             "input_tokens": 0, "output_tokens": 300, "cache_creation_tokens": 0, "cache_read_tokens": 0},
        ]
        model_rows = [
            {"fact_id": "f4", "model": "claude-opus-4-8", "input_tokens": 0, "output_tokens": 500, "cache_creation_tokens": 0, "cache_read_tokens": 0},
            {"fact_id": "f5", "model": "claude-opus-5", "input_tokens": 0, "output_tokens": 300, "cache_creation_tokens": 0, "cache_read_tokens": 0},
        ]
        out = build_hourly_family_facts(fact_rows, model_rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["model_family"], "opus")
        self.assertEqual(out[0]["output_tokens"], 800)

    def test_independent_recompute_of_unattributed_shortfall_from_raw_totals(self):
        """守恒复算：不调用 build_hourly_family_facts 内部逻辑，从原始字段独立算一遍差额。"""
        fact_total_output = 5000
        model_row_outputs = [1200, 800, 500]  # 三条 model 行
        expected_unattributed = fact_total_output - sum(model_row_outputs)
        fact_rows = [{
            "fact_id": "f6", "agent": "codex", "window_start": "2026-09-14T00:00:00Z", "window_end": "2026-09-14T01:00:00Z",
            "input_tokens": 0, "output_tokens": fact_total_output, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        }]
        model_rows = [
            {"fact_id": "f6", "model": "gpt-6-astra", "input_tokens": 0, "output_tokens": model_row_outputs[0], "cache_creation_tokens": 0, "cache_read_tokens": 0},
            {"fact_id": "f6", "model": "gpt-5.6-luna", "input_tokens": 0, "output_tokens": model_row_outputs[1], "cache_creation_tokens": 0, "cache_read_tokens": 0},
            {"fact_id": "f6", "model": "codex-auto-review", "input_tokens": 0, "output_tokens": model_row_outputs[2], "cache_creation_tokens": 0, "cache_read_tokens": 0},
        ]
        out = build_hourly_family_facts(fact_rows, model_rows)
        by_family = {row["model_family"]: row for row in out}
        self.assertEqual(by_family["unattributed"]["output_tokens"], expected_unattributed)
        self.assertGreater(expected_unattributed, 0)


if __name__ == "__main__":
    unittest.main()
