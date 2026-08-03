"""`scripts/merge_pr.sh` 的合并门禁判定（PM 2026-08-03 决策 A 方案）。

背景：免费私有仓库没有服务端 branch protection（GitHub 403：需 Pro 或转公开），
「全量交给 PR CI」的强制性改由仓库内机制承担：本脚本是 PR 合并的唯一入口，
四个必需 CI check 全部 SUCCESS 才执行合并；`bash_guard.sh` 拦截裸 `gh pr merge`。

判定的失效方向和 stop_gate 一样是「静默放行」，所以每条拒绝路径都要有用例，
且「通过」必须有结构下限——核对数必须正好是 4，缺席不等于通过。
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "merge_pr.sh"

ALLOW = 0
BLOCK = 2

ALL_GREEN = (
    "Python\tSUCCESS\n"
    "Cloudflare Worker\tSUCCESS\n"
    "iOS Swift\tSUCCESS\n"
    "macOS Swift\tSUCCESS\n"
)


class MergeGateTestCase(unittest.TestCase):
    def _run(self, args: list[str], rollup: str | None) -> subprocess.CompletedProcess[str]:
        env = {"PATH": "/usr/bin:/bin", "AIUSAGE_MERGE_GATE_DRYRUN": "1"}
        if rollup is not None:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".tsv", delete=False, encoding="utf-8"
            )
            self.addCleanup(Path(tmp.name).unlink)
            tmp.write(rollup)
            tmp.close()
            env["AIUSAGE_MERGE_GATE_ROLLUP"] = tmp.name
        return subprocess.run(
            [str(SCRIPT), *args], capture_output=True, text=True, env=env
        )


class TestMergeGateRefusals(MergeGateTestCase):
    def test_refuses_when_a_required_check_failed(self) -> None:
        rollup = ALL_GREEN.replace("Cloudflare Worker\tSUCCESS", "Cloudflare Worker\tFAILURE")
        result = self._run(["7"], rollup)
        self.assertEqual(result.returncode, BLOCK, result.stdout)
        self.assertIn("Cloudflare Worker", result.stderr)
        self.assertNotIn("MERGE-EXEC", result.stdout, "红着的 check 不许触发合并")

    def test_refuses_when_a_required_check_is_pending(self) -> None:
        rollup = ALL_GREEN.replace("Python\tSUCCESS", "Python\tPENDING")
        result = self._run(["7"], rollup)
        self.assertEqual(result.returncode, BLOCK)
        self.assertIn("Python", result.stderr)
        self.assertNotIn("MERGE-EXEC", result.stdout)

    def test_refuses_when_a_required_check_is_absent(self) -> None:
        """缺席不等于通过——checks 还没注册时的 rollup 只有 3 条甚至 0 条。"""
        rollup = ALL_GREEN.replace("iOS Swift\tSUCCESS\n", "")
        result = self._run(["7"], rollup)
        self.assertEqual(result.returncode, BLOCK)
        self.assertIn("iOS Swift", result.stderr)
        self.assertNotIn("MERGE-EXEC", result.stdout)

    def test_refuses_on_empty_rollup(self) -> None:
        result = self._run(["7"], "")
        self.assertEqual(result.returncode, BLOCK)
        self.assertNotIn("MERGE-EXEC", result.stdout)

    def test_refuses_admin_bypass(self) -> None:
        result = self._run(["7", "--admin"], ALL_GREEN)
        self.assertEqual(result.returncode, BLOCK)
        self.assertIn("--admin", result.stderr)
        self.assertNotIn("MERGE-EXEC", result.stdout)

    def test_refuses_without_pr_number(self) -> None:
        result = self._run([], None)
        self.assertEqual(result.returncode, BLOCK)
        self.assertIn("用法", result.stderr)


class TestMergeGatePasses(MergeGateTestCase):
    def test_merges_when_all_four_required_checks_succeed(self) -> None:
        result = self._run(["7", "--merge", "--delete-branch"], ALL_GREEN)
        self.assertEqual(result.returncode, ALLOW, result.stderr)
        self.assertIn("MERGE-EXEC 7 --merge --delete-branch", result.stdout)

    def test_extra_checks_do_not_confuse_the_gate(self) -> None:
        result = self._run(["7"], ALL_GREEN + "some-future-check\tFAILURE\n")
        self.assertEqual(result.returncode, ALLOW, result.stderr)
        self.assertIn("MERGE-EXEC", result.stdout)


if __name__ == "__main__":
    unittest.main()
