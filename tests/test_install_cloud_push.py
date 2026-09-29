from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_cloud_push.sh"
GIT_SPEC = "git+https://github.com/Moshuiwang/aiusage@main"

# 假 python3（sh 实现，避免 env 解析回自己）：pip install 时把 argv 逐行记下；
# -c 调用（查 user bin 目录）返回 shim 目录；pip 失败用 SHIM_PIP_FAIL 触发。
PY_SHIM = """#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  printf '%s\\n' "$*" >> "$SHIM_RECORD"
  [ -n "$SHIM_PIP_FAIL" ] && exit 1
  exit 0
fi
if [ "$1" = "-c" ]; then dirname "$0"; fi
exit 0
"""
HOOK_SHIM = '#!/bin/sh\necho "$@" >> "$SHIM_RECORD.hook"\n'


class TestInstallCloudPush(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("python3", PY_SHIM), ("ai-usage-widget", HOOK_SHIM)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.record = root / "record.txt"
        # 无 checkout：脚本副本的上级目录没有 pyproject.toml。
        scripts = root / "nocheckout" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, scripts / SCRIPT.name)
        self.nocheckout = scripts / SCRIPT.name

    def run_script(self, script: Path, **extra_env):
        env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": self.tmp.name, "SHIM_RECORD": str(self.record)}
        env.update(extra_env)
        proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        pips = self.record.read_text().splitlines() if self.record.exists() else []
        return proc, pips

    def test_no_checkout_installs_from_public_github_main(self) -> None:
        proc, pips = self.run_script(self.nocheckout)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(pips), 1, "应恰好执行一次 pip install")
        self.assertTrue(pips[0].endswith(f" {GIT_SPEC}"), pips[0])
        self.assertTrue(Path(str(self.record) + ".hook").exists(), "装完应继续写入 Stop hook")

    def test_package_ref_selects_git_ref(self) -> None:
        _, pips = self.run_script(self.nocheckout, AI_USAGE_PACKAGE_REF="v1.2")
        self.assertEqual(len(pips), 1)
        self.assertTrue(pips[0].endswith(" git+https://github.com/Moshuiwang/aiusage@v1.2"), pips[0])

    def test_checkout_is_installed_instead_of_github(self) -> None:
        proc, pips = self.run_script(SCRIPT)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(pips), 1)
        self.assertTrue(pips[0].endswith(f" {REPO}"), pips[0])
        self.assertNotIn("github.com", pips[0])

    def test_explicit_package_spec_wins(self) -> None:
        _, pips = self.run_script(self.nocheckout, AI_USAGE_PACKAGE_SPEC="pkg-from-spec", AI_USAGE_PACKAGE_REF="v9")
        self.assertEqual(len(pips), 1)
        self.assertTrue(pips[0].endswith(" pkg-from-spec"), pips[0])
        _, pips = self.run_script(SCRIPT, AI_USAGE_PACKAGE_SPEC="pkg-from-spec")
        self.assertTrue(pips[-1].endswith(" pkg-from-spec"), pips[-1])

    def test_pip_failure_exits_zero_and_skips_hook(self) -> None:
        proc, pips = self.run_script(self.nocheckout, SHIM_PIP_FAIL="1")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(pips), 1, "失败路径也必须真的尝试过安装")
        self.assertIn("失败", proc.stderr)
        self.assertFalse(Path(str(self.record) + ".hook").exists())


if __name__ == "__main__":
    unittest.main()
