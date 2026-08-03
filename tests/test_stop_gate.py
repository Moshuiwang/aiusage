"""`scripts/stop_gate.sh` 的收口门禁判定（Issue #86）。

这个门禁自己一直没有回归网：#83 记录过它的残留检查会自匹配调用方 shell，
但当时的修法是**改验证方法**，脚本本身没加任何防护——教训被记录了，没有被机制化。

被守护的两件事：

- **改动触发**：`src/` 或 `tests/` 有改动就必须跑 Python 全量，不绿就阻止收口；
  `cloudflare/` 有改动必须强制显式交代。
- **残留盘点**：`git status` 干净不等于收口干净。判据必须是**可执行文件 + argv**，
  不能是 `pgrep -f` 那种整条命令行文本匹配——后者会把「只是提到这个词组」的
  调用方 shell 报成残留（误报），同时漏掉命令行里没有 `wrangler` 子串的 worker 进程（漏报）。

残留判定通过 `AIUSAGE_STOP_GATE_PS` 注入固定进程表来离线回归；
另有一条用**真实进程**跑的用例，防止「注入路径能过、真实路径不行」。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_GATE = REPO_ROOT / "scripts" / "stop_gate.sh"

# 进程表的列与 `ps -eo pid=,ppid=,comm=,args=` 一致：pid ppid comm args
SELF_PID = "9001"
BASE_SNAPSHOT = [
    f"{SELF_PID} 9000 bash /bin/bash scripts/stop_gate.sh",
    "9000 8999 node /usr/bin/node /opt/claude/cli.js",
    "8999 1 bash -bash",
]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class StopGateTestCase(unittest.TestCase):
    """在一次性临时仓库里构造改动与进程表，断言门禁判定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "docs").mkdir()

        # 门禁用 dirname 定位仓库根，所以脚本要放进临时仓库的同名位置。
        target = self.repo / "scripts" / "stop_gate.sh"
        shutil.copy2(STOP_GATE, target)
        target.chmod(0o755)

        (self.repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
        self._write_passing_test()

        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- 夹具 ---------------------------------------------------------------

    def _write_passing_test(self) -> None:
        (self.repo / "tests" / "test_seed.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n"
            "    def test_ok(self) -> None:\n        self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )

    def _write_failing_test(self) -> None:
        (self.repo / "tests" / "test_seed.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n"
            "    def test_broken(self) -> None:\n        self.assertEqual(1, 2)\n",
            encoding="utf-8",
        )

    def _run(self, snapshot: list[str] | None = None, use_real_ps: bool = False) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "LC_ALL": "C.UTF-8"}
        if use_real_ps:
            env.pop("AIUSAGE_STOP_GATE_PS", None)
        else:
            path = Path(self._tmp.name) / "ps.txt"
            path.write_text("\n".join(BASE_SNAPSHOT if snapshot is None else snapshot) + "\n", encoding="utf-8")
            env["AIUSAGE_STOP_GATE_PS"] = str(path)
            env["AIUSAGE_STOP_GATE_SELF_PID"] = SELF_PID
        return subprocess.run(
            [str(self.repo / "scripts" / "stop_gate.sh")],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )


class TestChangeScope(StopGateTestCase):
    def test_clean_worktree_passes(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_docs_only_change_passes(self) -> None:
        (self.repo / "docs" / "note.md").write_text("changed\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_src_change_with_green_tests_passes(self) -> None:
        (self.repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_src_change_with_red_tests_blocks(self) -> None:
        (self.repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        self._write_failing_test()
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("Python 测试未通过", result.stderr)

    def test_cloudflare_change_demands_explicit_worker_evidence(self) -> None:
        """cloudflare/ 有改动仍然阻止收口，但索要的证据是 targeted 测试 + PR CI（2026-08-03 口径）。

        不再索要本地全量 verify.sh：全量套件由 PR CI 承担（合并唯一入口
        scripts/merge_pr.sh 强制四个 check 全 SUCCESS，见 test_merge_pr_gate），
        本地全量降级为可选复核。
        """
        path = self.repo / "cloudflare" / "native-worker" / "src" / "index.ts"
        path.parent.mkdir(parents=True)
        path.write_text("export default {};\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("targeted", result.stderr)
        self.assertIn("PR CI", result.stderr)
        self.assertIn(".skip-stop-gate", result.stderr)
        self.assertNotIn(
            "请执行：\n    scripts/verify.sh",
            result.stderr,
            "旧口径的「必须本地全量」措辞不应再出现",
        )

    def test_skip_marker_is_one_shot(self) -> None:
        (self.repo / ".claude").mkdir()
        marker = self.repo / ".claude" / ".skip-stop-gate"
        marker.write_text("", encoding="utf-8")
        (self.repo / "src" / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        self._write_failing_test()

        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "跳过标记必须是一次性的")


class TestResidueDetection(StopGateTestCase):
    """残留判定：既不许误报调用方 shell，也不许漏报真正的开发服务。"""

    def test_caller_shell_merely_mentioning_the_phrase_is_not_residue(self) -> None:
        """#86 问题一：`bash -c` 的 argv 就是整段脚本文本。

        只要命令文本里出现那个词组——比如一条讨论它的命令——`pgrep -f` 就会命中，
        而 `ps -p <PID>` 查过去进程根本不是开发服务。
        """
        result = self._run([
            *BASE_SNAPSHOT,
            "9100 8999 bash bash -c echo 检查一下 wrangler dev 有没有残留",
            "9101 8999 python3 python3 -c print('wrangler dev')",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_self_and_ancestors_are_never_reported(self) -> None:
        """hook 自己是 Claude Code（node）拉起来的，node 的 argv 可能带着这段文本。"""
        result = self._run([
            f"{SELF_PID} 9000 bash /bin/bash scripts/stop_gate.sh",
            "9000 8999 node /usr/bin/node /opt/claude/cli.js --print 排查 wrangler dev 残留",
            "8999 1 bash -bash",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plain_wrangler_dev_is_residue(self) -> None:
        result = self._run([*BASE_SNAPSHOT, "9200 8999 wrangler wrangler dev --local"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("9200", result.stderr)

    def test_node_wrangler_dist_cli_dev_is_residue(self) -> None:
        """#86 验收：`node .../wrangler-dist/cli.js dev` 的命令行里没有字面「wrangler dev」。"""
        result = self._run([
            *BASE_SNAPSHOT,
            "9201 8999 node node /repo/node_modules/wrangler/wrangler-dist/cli.js dev --local",
        ])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("9201", result.stderr)

    def test_wrangler_deploy_is_not_residue(self) -> None:
        """判据要的是独立的 `dev` 参数，不是「argv 里出现过 dev 这三个字母」。"""
        result = self._run([
            *BASE_SNAPSHOT,
            "9202 8999 node node /repo/node_modules/wrangler/wrangler-dist/cli.js deploy",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_workerd_with_live_parent_is_not_residue(self) -> None:
        """#86 验收第三条：workerd 有活着的父进程时**不算**残留。

        它永远是 wrangler dev / vitest-miniflare 的子进程，没有独立生命周期。
        把它算成残留，等于每次跑完 Worker 测试都收不了口，门禁很快会被绕开。
        """
        result = self._run([
            *BASE_SNAPSHOT,
            "9300 9299 node node /repo/node_modules/vitest/vitest.mjs run",
            "9301 9300 workerd workerd serve --socket-addr=entry=127.0.0.1:0 /tmp/config.bin",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_orphan_workerd_is_residue(self) -> None:
        """父进程已退出的 workerd 谁也不属于——正是那种占着端口没人发现的泄漏。"""
        result = self._run([
            *BASE_SNAPSHOT,
            "9302 1 workerd workerd serve --socket-addr=entry=127.0.0.1:8787 /tmp/config.bin",
        ])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("9302", result.stderr)

    def test_residue_blocks_even_when_worktree_is_clean(self) -> None:
        """`git status` 干净不等于收口干净——这正是 #68 补记二的那条教训。"""
        result = self._run([*BASE_SNAPSHOT, "9203 8999 wrangler wrangler dev"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("残留", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "需要 bash 才能造出真实进程")
    def test_real_process_is_detected_through_the_real_ps_path(self) -> None:
        """注入路径能过不代表真实路径能过：这条用真实进程 + 真实 `ps` 跑一遍。

        用 bash 的一份副本冒充 `node`（`comm` 取的是可执行文件名），argv 摆成
        `node .../wrangler-dist/cli.js dev` 的形状——这是最难抓的那一种。
        """
        fake_dir = Path(self._tmp.name) / "node_modules" / "wrangler" / "wrangler-dist"
        fake_dir.mkdir(parents=True)
        fake_node = fake_dir / "node"
        shutil.copy2(shutil.which("bash"), fake_node)
        fake_node.chmod(0o755)

        # `-c "sleep 30"` 会被 bash 优化成 exec，进程名变回 sleep、argv 也塌掉，
        # 伪装就没了（这正是本条用例第一版被静默跳过的原因）。多一条命令即可阻止该优化。
        process = subprocess.Popen(
            [str(fake_node), "-c", "sleep 30; :", str(fake_dir / "cli.js"), "dev"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # 等进程真的出现在进程表里再盘点，不然测的是「还没起来」。
            for _ in range(50):
                listing = subprocess.run(
                    ["ps", "-o", "args=", "-p", str(process.pid)],
                    capture_output=True, text=True,
                )
                if "wrangler-dist" in listing.stdout:
                    break
                time.sleep(0.1)
            else:
                self.skipTest("进程表里始终看不到伪装进程，跳过真实路径用例")

            result = self._run(use_real_ps=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn(str(process.pid), result.stderr)
        finally:
            process.send_signal(signal.SIGKILL)
            process.wait(timeout=10)

    def test_real_ps_path_is_quiet_when_only_the_command_text_mentions_it(self) -> None:
        """#86 验收：把那个词组写进调用方命令文本但不起任何进程 → 必须不报。

        这条**不注入进程表**，走真实 `ps`：调用方是一个 argv 里带着
        「wrangler dev」的 bash，正是 #83 踩过的那个自匹配现场。
        """
        script = (
            f"cd {self.repo} && "
            f"'{self.repo}/scripts/stop_gate.sh'  # 这条命令自己提到了 wrangler dev"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        self.assertNotIn("残留", result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
