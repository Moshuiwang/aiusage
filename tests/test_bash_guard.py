"""`scripts/bash_guard.sh` 的 PreToolUse 拦截判定（Issue #86）。

这个门禁拦的是 #68 里重复踩过 3 次以上的两种手法：`pkill -f` 与
「`until`/`while` + `pgrep` 等待循环」。判据故意收窄——宁可漏拦也不要误伤日常命令——
而「收窄」正是需要回归网的地方：两条正则里任何一处放宽或收紧，
都会在没有任何信号的情况下改变门禁行为。

在本 Issue 之前，`grep -rln "bash_guard" tests/` 零命中。
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASH_GUARD = REPO_ROOT / "scripts" / "bash_guard.sh"

ALLOW = 0
BLOCK = 2


def _run(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BASH_GUARD)],
        input=payload,
        capture_output=True,
        text=True,
    )


def _hook_input(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


class TestPkillGuard(unittest.TestCase):
    """`pkill -f` 按命令行关键字杀进程，历史上三次把调用方自己杀掉。"""

    def test_blocks_plain_pkill_dash_f(self) -> None:
        result = _run(_hook_input("pkill -f wrangler"))
        self.assertEqual(result.returncode, BLOCK, result.stdout)
        self.assertIn("bash_guard 拦截", result.stderr)
        self.assertIn("fuser -k", result.stderr, "拦下来必须给出替代做法")

    def test_blocks_pkill_after_a_separator(self) -> None:
        """命令位置不只有行首：`;`、`&&`、`|`、`(` 之后同样是命令位置。"""
        for command in (
            "echo start; pkill -f node",
            "true && pkill -f node",
            "( pkill -f node )",
        ):
            with self.subTest(command=command):
                self.assertEqual(_run(_hook_input(command)).returncode, BLOCK, command)

    def test_blocks_pkill_with_flags_before_dash_f(self) -> None:
        self.assertEqual(_run(_hook_input("pkill -TERM -f wrangler")).returncode, BLOCK)

    def test_allows_merely_mentioning_pkill_in_text(self) -> None:
        """提交信息、注释、文档里**提到**这条命令不该被拦——判据锚定在命令位置。"""
        for command in (
            'git commit -m "改用 fuser -k，不再用 pkill -f"',
            "echo '不要用 pkill -f'",
            "grep -rn 'pkill -f' docs/",
        ):
            with self.subTest(command=command):
                self.assertEqual(_run(_hook_input(command)).returncode, ALLOW, command)

    def test_allows_pkill_without_dash_f(self) -> None:
        """按进程名杀（`pkill wrangler`）不是本门禁要拦的手法。"""
        self.assertEqual(_run(_hook_input("pkill wrangler")).returncode, ALLOW)


class TestPgrepWaitLoopGuard(unittest.TestCase):
    """`pgrep -f` 会匹配到循环自身，条件永真——#68 留下过 7 个僵尸循环。"""

    def test_blocks_until_pgrep_loop(self) -> None:
        result = _run(_hook_input("until pgrep -f wrangler; do sleep 2; done"))
        self.assertEqual(result.returncode, BLOCK, result.stdout)
        self.assertIn("bash_guard 拦截", result.stderr)
        self.assertIn("run_in_background", result.stderr, "拦下来必须给出替代做法")

    def test_blocks_while_pgrep_loop(self) -> None:
        self.assertEqual(
            _run(_hook_input("while ! pgrep wrangler > /dev/null; do sleep 1; done")).returncode,
            BLOCK,
        )

    def test_allows_read_only_pgrep(self) -> None:
        """一次性盘点是合法用途，不该被拦。"""
        for command in ("pgrep -af wrangler", "pgrep -f vitest | head"):
            with self.subTest(command=command):
                self.assertEqual(_run(_hook_input(command)).returncode, ALLOW, command)

    def test_allows_wait_loop_without_pgrep(self) -> None:
        """用文件状态 / 端口 / 退出码做判据的循环正是门禁推荐的写法。"""
        self.assertEqual(
            _run(_hook_input("for i in $(seq 1 30); do [ -f done.txt ] && break; sleep 1; done")).returncode,
            ALLOW,
        )


class TestRawMergeGuard(unittest.TestCase):
    """裸 `gh pr merge` 必须走 `scripts/merge_pr.sh`（PM 2026-08-03 决策 A 方案）。

    免费私有仓库没有服务端 branch protection，「CI 全绿才能合并」的强制性
    由 merge_pr.sh + 本拦截共同承担。merge_pr.sh 内部的 gh 调用不经过本 hook
    （hook 只扫 Bash 工具的命令文本），所以拦掉裸调用不会拦掉唯一入口自己。
    """

    def test_blocks_plain_gh_pr_merge(self) -> None:
        result = _run(_hook_input("gh pr merge 99 --merge --delete-branch"))
        self.assertEqual(result.returncode, BLOCK, result.stdout)
        self.assertIn("merge_pr.sh", result.stderr, "拦下来必须给出唯一入口")

    def test_blocks_gh_pr_merge_after_a_separator(self) -> None:
        for command in (
            "git push && gh pr merge 99",
            "true; gh pr merge 99 --squash",
            "( gh pr merge 99 )",
        ):
            with self.subTest(command=command):
                self.assertEqual(_run(_hook_input(command)).returncode, BLOCK, command)

    def test_allows_merge_pr_script(self) -> None:
        self.assertEqual(_run(_hook_input("scripts/merge_pr.sh 99 --merge")).returncode, ALLOW)

    def test_allows_merely_mentioning_the_phrase_in_text(self) -> None:
        self.assertEqual(
            _run(_hook_input('echo "以后不要直接 gh pr merge，改走脚本"')).returncode,
            ALLOW,
        )

    def test_allows_other_gh_pr_subcommands(self) -> None:
        for command in ("gh pr view 99", "gh pr checks 99 --watch", "gh pr create --draft"):
            with self.subTest(command=command):
                self.assertEqual(_run(_hook_input(command)).returncode, ALLOW, command)


class TestGuardFailsOpen(unittest.TestCase):
    """门禁本身不能把工作卡死：输入解析不了时一律放行。"""

    def test_malformed_json_is_allowed(self) -> None:
        self.assertEqual(_run("not json at all").returncode, ALLOW)

    def test_empty_input_is_allowed(self) -> None:
        self.assertEqual(_run("").returncode, ALLOW)

    def test_missing_command_field_is_allowed(self) -> None:
        self.assertEqual(_run(json.dumps({"tool_name": "Bash", "tool_input": {}})).returncode, ALLOW)

    def test_ordinary_command_is_allowed(self) -> None:
        self.assertEqual(_run(_hook_input("scripts/verify.sh --full")).returncode, ALLOW)


class TestHeredocHandling(unittest.TestCase):
    def test_forbidden_phrases_inside_heredoc_are_only_text(self) -> None:
        command = """python3 <<'PY'
pkill -f wrangler
while pgrep wrangler; do echo waiting; done
gh pr merge 99
PY"""
        self.assertEqual(_run(_hook_input(command)).returncode, ALLOW)

    def test_real_command_after_heredoc_is_still_blocked(self) -> None:
        command = """cat <<'EOF'
文档正文里提到 pkill -f
EOF
pkill -f wrangler"""
        self.assertEqual(_run(_hook_input(command)).returncode, BLOCK)


if __name__ == "__main__":
    unittest.main()
