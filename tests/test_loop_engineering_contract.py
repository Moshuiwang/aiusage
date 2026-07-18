from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / ".agents/skills/loop-planner/references/plan-contract-v2.md"
PLANNER = ROOT / ".agents/skills/loop-planner/SKILL.md"
EXECUTOR = ROOT / ".agents/skills/loop-executor/SKILL.md"


class LoopEngineeringContractTests(unittest.TestCase):
    def test_contract_defines_opt_in_merge_modes_and_manual_default(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")

        self.assertIn("merge_pr: manual", text)
        self.assertIn("when_no_open_p0_p1", text)
        self.assertIn("review_rounds", text)
        self.assertIn("high 默认两轮", text)
        self.assertIn("未声明", text)
        self.assertIn("manual", text)
        self.assertIn("按 risk 要求的 Review", text)
        self.assertIn("冲突 Plan 无效", text)
        self.assertIn("approval.status: approved", text)
        self.assertIn("仓库要求的 PR 审批", text)
        self.assertIn("merge_method", text)
        self.assertIn("squash", text)
        self.assertIn("head SHA 绑定", text)
        self.assertIn("修复或证伪", text)
        self.assertIn("plan_digest", text)
        self.assertIn("approvers", text)
        self.assertIn("contract_digests", text)
        self.assertIn("approve owner/repo#N revision R plan sha256:", text)
        self.assertIn("任何 PR head SHA 变化", text)
        self.assertIn("plan_issue", text)
        self.assertIn("required_issues", text)
        self.assertIn("RFC 8785", text)
        self.assertIn("只能有一个", text)
        self.assertIn("重复 key", text)
        self.assertIn("owner/repo#N", text)
        self.assertIn("同一 Codex 任务", text)

    def test_planner_requires_explicit_merge_authorization_and_human_approval(self) -> None:
        text = PLANNER.read_text(encoding="utf-8")

        self.assertIn("authorization.merge_pr", text)
        self.assertIn("when_no_open_p0_p1", text)
        self.assertIn("review_rounds", text)
        self.assertIn("不批准自己的 Plan", text)

    def test_executor_merges_only_on_same_clean_head_without_open_p0_p1(self) -> None:
        text = EXECUTOR.read_text(encoding="utf-8")

        self.assertIn("authorization.merge_pr", text)
        self.assertIn("when_no_open_p0_p1", text)
        self.assertIn("最新 PR head SHA", text)
        self.assertIn("未解决 P0/P1", text)
        self.assertIn("合并结果不确定", text)
        self.assertIn("manual", text)
        self.assertIn("冲突 Plan 无效", text)
        self.assertIn("仓库要求的 PR 审批", text)
        self.assertIn("--match-head-commit", text)
        self.assertIn("逐项 checklist", text)
        self.assertIn("重新回读仓库规则", text)
        self.assertIn("plan_digest", text)
        self.assertIn("contract_digests", text)
        self.assertIn("原 head OID", text)
        self.assertIn("immutable merge commit", text)
        self.assertIn("任何 PR head SHA 变化", text)
        self.assertIn("baseRefName", text)
        self.assertIn("获批 base_branch", text)
        self.assertIn("merge commit 已进入", text)
        self.assertIn("merge queue", text)
        self.assertIn("auto-merge", text)
        self.assertIn("同步 merge", text)
        self.assertIn("required_issues", text)
        self.assertIn("当前 Plan Issue", text)
        self.assertIn("同一 Codex 任务", text)
        self.assertIn("required_review_rounds", text)
        self.assertIn("review_heads", text)


if __name__ == "__main__":
    unittest.main()
