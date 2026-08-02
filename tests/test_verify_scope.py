"""`scripts/verify.sh` 的改动面裁剪判定。

裁剪省下的是每次 3–4 分钟的 Worker 测试（#68 优化项 2），但它有一个危险的失败模式：
**判据算错时，该跑的测试不跑，而且没有任何信号**——脚本照样退出 0、照样打印
「证据等级 3」。那正是本项目最忌讳的假绿。

所以判定逻辑必须可独立验证，不能只能靠「跑一次全量看看对不对」。
`scripts/verify.sh --explain-scope` 只输出判定结果、不跑任何测试，本测试就断言它。

判定规则（保守优先，宁可多跑不可漏跑）：

- Worker 测试**只在改动面涉及 `cloudflare/` 时才跑**；
- 改动面 = 工作区未提交改动 ∪ 相对 base 的已提交改动，两者取并集；
- 改动面**无法确定**时（不在 git 仓库、拿不到 base）退回全量，不是退回跳过；
- `--full` 强制全量，`--python-only` 强制跳 Worker，两者都压过自动判定。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _explain_scope(cwd: Path, *extra_args: str) -> str:
    """跑 `verify.sh --explain-scope`，返回 stdout。"""
    result = subprocess.run(
        [str(VERIFY_SH), "--explain-scope", *extra_args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"--explain-scope 应当以 0 退出，实际 {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


class TestVerifyScope(unittest.TestCase):
    """在一次性临时仓库里构造改动，断言裁剪判定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")

        # 复刻仓库结构里与判定相关的几个顶层目录
        for rel in ("src/app.py", "tests/test_app.py", "cloudflare/worker.ts", "docs/note.md"):
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("seed\n", encoding="utf-8")

        # verify.sh 用 dirname 定位仓库根，所以要把它放进临时仓库的同名位置。
        # 必须在 seed commit **之前**放好并一起提交：否则它会以未跟踪文件的身份
        # 留在改动面里，让「无改动」这个场景根本不成立，测出来的判定也就没意义。
        scripts_dir = self.repo / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        target = scripts_dir / "verify.sh"
        target.write_text(VERIFY_SH.read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(0o755)
        self.verify = target

        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "seed")
        _git(self.repo, "branch", "-f", "verify-base")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _explain(self, *extra: str) -> str:
        result = subprocess.run(
            [str(self.verify), "--explain-scope", *extra],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={**os.environ, "AIUSAGE_VERIFY_BASE": "verify-base", "LC_ALL": "C.UTF-8"},
        )
        self.assertEqual(
            result.returncode,
            0,
            f"--explain-scope 应以 0 退出\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )
        return result.stdout

    def test_python_only_change_skips_worker(self) -> None:
        """只动 Python：Worker 那 3-4 分钟是纯浪费，必须跳过。"""
        (self.repo / "src" / "app.py").write_text("changed\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("worker=skip", out, out)
        self.assertIn("python=run", out, out)

    def test_cloudflare_change_runs_worker(self) -> None:
        """动了 cloudflare/：必须跑 Worker，漏跑就是假绿。"""
        (self.repo / "cloudflare" / "worker.ts").write_text("changed\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("worker=run", out, out)

    def test_committed_cloudflare_change_still_runs_worker(self) -> None:
        """改动已经 commit 时工作区是干净的——只看 git status 会漏掉它。

        这是裁剪最容易写错的地方：提交之后再跑 verify，Worker 被静默跳过。
        """
        (self.repo / "cloudflare" / "worker.ts").write_text("changed\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "worker change")
        out = self._explain()
        self.assertIn("worker=run", out, out)

    def test_docs_only_change_skips_worker(self) -> None:
        """纯文档改动不需要 Worker。"""
        (self.repo / "docs" / "note.md").write_text("changed\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("worker=skip", out, out)

    def test_no_change_runs_everything(self) -> None:
        """改动面为空时退回全量，不是退回跳过——保守优先。"""
        out = self._explain()
        self.assertIn("worker=run", out, out)

    def test_full_flag_overrides_auto_skip(self) -> None:
        """`--full` 压过自动判定。"""
        (self.repo / "src" / "app.py").write_text("changed\n", encoding="utf-8")
        out = self._explain("--full")
        self.assertIn("worker=run", out, out)

    def test_python_only_flag_overrides_auto_run(self) -> None:
        """`--python-only` 压过自动判定。"""
        (self.repo / "cloudflare" / "worker.ts").write_text("changed\n", encoding="utf-8")
        out = self._explain("--python-only")
        self.assertIn("worker=skip", out, out)

    def test_scope_decision_is_printed_with_reason(self) -> None:
        """判定必须带可读理由——静默裁剪等于静默漏跑。"""
        (self.repo / "src" / "app.py").write_text("changed\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("改动面", out, out)
        self.assertIn("src/app.py", out, out)

    def test_worker_source_only_change_skips_python(self) -> None:
        """只动 TS 源码：Python 测试不读那个目录，可以跳过。"""
        path = self.repo / "cloudflare" / "native-worker" / "src" / "read-model.ts"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "ts only")
        out = self._explain()
        self.assertIn("python=skip", out, out)
        self.assertIn("worker=run", out, out)

    def test_migrations_change_still_runs_python(self) -> None:
        """改 migrations 必须跑 Python：test_d1_schema_migration 直接读这些 .sql。

        这是「改了 cloudflare/ 就跳 Python」这种过宽判据会漏掉的第一类反例。
        """
        path = self.repo / "cloudflare" / "migrations" / "0008_x.sql"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("-- x\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("python=run", out, out)

    def test_worker_test_fixture_change_still_runs_python(self) -> None:
        """改 Worker 侧 test/ 下的 golden 与 fixture 必须跑 Python。

        那些文件由 Python 生成、被 Python 防陈旧守卫逐字段比对
        （test_value_golden_freshness / test_collector_payload_contract）。
        """
        path = self.repo / "cloudflare" / "native-worker" / "test" / "value_golden.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("python=run", out, out)

    def test_mixed_change_runs_both(self) -> None:
        """TS 源码 + Python 混合改动：两边都要跑，不许因为「大部分是 TS」就跳。"""
        ts = self.repo / "cloudflare" / "native-worker" / "src" / "read-model.ts"
        ts.parent.mkdir(parents=True, exist_ok=True)
        ts.write_text("changed\n", encoding="utf-8")
        (self.repo / "src" / "app.py").write_text("changed\n", encoding="utf-8")
        out = self._explain()
        self.assertIn("python=run", out, out)
        self.assertIn("worker=run", out, out)

    def test_unknown_base_falls_back_to_full(self) -> None:
        """拿不到 base 时退回全量。判据不可信就不许裁剪。"""
        result = subprocess.run(
            [str(self.verify), "--explain-scope"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AIUSAGE_VERIFY_BASE": "no-such-ref-xyz",
                "LC_ALL": "C.UTF-8",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("worker=run", result.stdout, result.stdout)


if __name__ == "__main__":
    unittest.main()
