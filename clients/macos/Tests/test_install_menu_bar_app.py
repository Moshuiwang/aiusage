import importlib.util
import sys
import unittest
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
        self.assertEqual(plan.bundle_id, "com.chunbai.aiusage.menubar.numeric")
        self.assertIn("<key>LSUIElement</key>", installer.render_info_plist(plan))
        self.assertIn("<true/>", installer.render_info_plist(plan))
        self.assertIn(
            "<string>com.chunbai.aiusage.menubar.numeric</string>",
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


if __name__ == "__main__":
    unittest.main()
