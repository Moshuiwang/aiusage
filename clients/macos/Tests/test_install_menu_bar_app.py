import importlib.util
import subprocess
import sys
import unittest
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path


def load_installer_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "install_menu_bar_app.py"
    spec = importlib.util.spec_from_file_location("install_menu_bar_app", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallMenuBarAppTests(unittest.TestCase):
    def test_default_install_plan_stays_out_of_documents(self):
        installer = load_installer_module()

        plan = installer.InstallPlan.default(
            repo_dir=Path("/Users/product/Documents/ai-usage-widget"),
            home=Path("/Users/product"),
            install_dir=None,
            runtime_dir=None,
        )

        self.assertEqual(plan.app_path, Path("/Applications/AI Usage Menu Bar.app"))
        self.assertEqual(
            plan.runtime_dir,
            Path("/Users/product/Library/Application Support/ai-usage-widget/macos-menu-bar"),
        )
        self.assertNotIn("Documents", str(plan.runtime_dir))
        self.assertNotIn("Documents", str(plan.config_path))
        self.assertEqual(plan.bundle_id, "com.chunbai.aiusage.menubar.app")
        self.assertIn("<key>LSUIElement</key>", installer.render_info_plist(plan))
        self.assertIn("<true/>", installer.render_info_plist(plan))
        self.assertIn(
            "<string>com.chunbai.aiusage.menubar.app</string>",
            installer.render_info_plist(plan),
        )
        self.assertIn("<key>CFBundleIconFile</key>", installer.render_info_plist(plan))
        self.assertIn("AIUsageMenuBar", installer.render_info_plist(plan))

    def test_install_plan_includes_bundle_icon(self):
        installer = load_installer_module()

        plan = installer.InstallPlan.default(
            repo_dir=Path("/Users/product/Documents/ai-usage-widget"),
            home=Path("/Users/product"),
            install_dir=None,
            runtime_dir=None,
        )

        self.assertEqual(
            plan.source_icon_path,
            Path("/Users/product/Documents/ai-usage-widget/clients/macos/Resources/AIUsageMenuBar.icns"),
        )
        self.assertEqual(
            plan.bundle_icon_path,
            Path("/Applications/AI Usage Menu Bar.app/Contents/Resources/AIUsageMenuBar.icns"),
        )

    def test_script_default_repo_dir_is_workspace_root(self):
        installer = load_installer_module()

        self.assertEqual(
            installer.default_repo_dir(),
            Path(__file__).resolve().parents[3],
        )

    def test_install_uses_swift_reported_binary_instead_of_stale_legacy_path(self):
        installer = load_installer_module()
        with tempfile.TemporaryDirectory(prefix="mac-display-installer-") as directory:
            root = Path(directory)
            plan = installer.InstallPlan.default(repo_dir=root, home=root, install_dir=root / "Apps", runtime_dir=root / "runtime")
            legacy = plan.package_dir / ".build" / "release" / installer.EXECUTABLE_NAME
            actual_dir = plan.package_dir / ".build" / "out" / "Products" / "Release"
            legacy.parent.mkdir(parents=True)
            actual_dir.mkdir(parents=True)
            legacy.write_bytes(b"old version")
            (actual_dir / installer.EXECUTABLE_NAME).write_bytes(b"current built version")
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                return SimpleNamespace(stdout=str(actual_dir) + "\n", returncode=0)

            with patch.object(installer.subprocess, "run", side_effect=run):
                installer.install(plan, server_url=None, token=None, dashboard_url=None, dry_run=False)
            self.assertEqual(plan.executable_path.read_bytes(), b"current built version")
            # #178：render_info_plist 现在读取 git 构建号/commit（各一次 subprocess），
            # 插在「构建产物」和「codesign」之间；fake run 对任何命令都返回同一 stdout，
            # 这里只断言调用顺序与总数，不断言 Info.plist 的具体版本内容。
            self.assertEqual(len(commands), 5)
            self.assertEqual(commands[0], ["swift", "build", "-c", "release"])
            self.assertEqual(commands[1], ["swift", "build", "-c", "release", "--show-bin-path"])
            self.assertEqual(commands[2][:2], ["git", "rev-list"])
            self.assertEqual(commands[3][:2], ["git", "rev-parse"])
            self.assertEqual(commands[4][0], "codesign")

    def test_render_info_plist_uses_version_file_and_git_metadata(self):
        installer = load_installer_module()
        with tempfile.TemporaryDirectory(prefix="mac-display-installer-") as directory:
            root = Path(directory)
            package_dir = root / "clients" / "macos"
            package_dir.mkdir(parents=True)
            (package_dir / "VERSION").write_text("2.0.0\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "--allow-empty", "-m", "one", "-q"],
                cwd=root, check=True,
            )
            subprocess.run(
                ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "--allow-empty", "-m", "two", "-q"],
                cwd=root, check=True,
            )
            commit_sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
            ).stdout.strip()

            plan = installer.InstallPlan.default(repo_dir=root, home=root, install_dir=None, runtime_dir=None)
            plist = installer.render_info_plist(plan)

            self.assertIn("<key>CFBundleShortVersionString</key>\n  <string>2.0.0</string>", plist)
            self.assertIn("<key>CFBundleVersion</key>\n  <string>2</string>", plist)
            self.assertIn(f"<key>AIUsageGitCommit</key>\n  <string>{commit_sha}</string>", plist)

    def test_render_info_plist_falls_back_when_git_is_unavailable(self):
        installer = load_installer_module()
        with tempfile.TemporaryDirectory(prefix="mac-display-installer-") as directory:
            root = Path(directory)
            package_dir = root / "clients" / "macos"
            package_dir.mkdir(parents=True)
            (package_dir / "VERSION").write_text("2.0.0\n", encoding="utf-8")
            # 故意不 `git init`：模拟 git 不可用/不是仓库，必须回退而不是让安装失败。

            plan = installer.InstallPlan.default(repo_dir=root, home=root, install_dir=None, runtime_dir=None)
            plist = installer.render_info_plist(plan)

            self.assertIn("<key>CFBundleVersion</key>\n  <string>0</string>", plist)
            self.assertNotIn("AIUsageGitCommit", plist)

    def test_sign_app_bundle_binds_the_stable_bundle_identity(self):
        installer = load_installer_module()
        plan = installer.InstallPlan.default(
            repo_dir=Path("/Users/product/Documents/ai-usage-widget"),
            home=Path("/Users/product"),
            install_dir=None,
            runtime_dir=None,
        )
        commands = []
        original_run = installer.subprocess.run
        installer.subprocess.run = lambda command, check: commands.append((command, check))
        try:
            installer.sign_app_bundle(plan)
        finally:
            installer.subprocess.run = original_run

        self.assertEqual(
            commands,
            [
                (
                    [
                        "codesign",
                        "--force",
                        "--sign",
                        "-",
                        "--identifier",
                        "com.chunbai.aiusage.menubar.app",
                        "/Applications/AI Usage Menu Bar.app",
                    ],
                    True,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
