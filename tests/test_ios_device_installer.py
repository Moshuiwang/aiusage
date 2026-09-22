from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "mobile/ios-xcode/install_device_with_live_config.py"
spec = importlib.util.spec_from_file_location("ios_device_installer", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class IOSDeviceInstallerTests(unittest.TestCase):
    def test_device_selection_is_used_for_build_install_and_launch(self):
        with mock.patch.object(installer, "read_token", return_value="synthetic-test-secret"), \
             mock.patch.object(installer, "verify_production_summary"), \
             mock.patch.object(installer, "write_temp_xcconfig", return_value=pathlib.Path("/tmp/ios-test-secret")), \
             mock.patch.object(installer, "build_app", return_value=pathlib.Path("/tmp/app")) as build, \
             mock.patch.object(installer, "verify_built_app_config"), \
             mock.patch.object(installer, "install_app") as install, \
             mock.patch.object(installer, "launch_app") as launch, \
             mock.patch.object(installer, "cleanup_secret_files"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["--device-id", "current-phone"]), 0)
        self.assertEqual(build.call_args.kwargs["device_id"], "current-phone")
        self.assertEqual(install.call_args.kwargs["devicectl_id"], "current-phone")
        self.assertEqual(launch.call_args.kwargs["devicectl_id"], "current-phone")

    def test_build_returns_only_its_own_explicit_derived_data_product(self):
        with tempfile.TemporaryDirectory(prefix="ios-installer-test-") as directory:
            root = pathlib.Path(directory)
            stale = root / "unrelated.app"
            stale.mkdir()
            seen = []
            def build(command):
                seen.append(command)
                if "-derivedDataPath" in command:
                    destination = pathlib.Path(command[command.index("-derivedDataPath") + 1])
                    (destination / "Build/Products/Debug-iphoneos/AIUsageMobileApp.app").mkdir(parents=True)
            with mock.patch.object(installer, "run", side_effect=build), \
                 mock.patch.object(installer, "latest_built_app", return_value=stale, create=True), \
                 contextlib.redirect_stdout(io.StringIO()):
                actual = installer.build_app(root / "project.xcodeproj", "phone", root / "secret.xcconfig")
            self.assertEqual(len(seen), 1)
            self.assertIn("-derivedDataPath", seen[0])
            destination = pathlib.Path(seen[0][seen[0].index("-derivedDataPath") + 1])
            self.assertEqual(actual, destination / "Build/Products/Debug-iphoneos/AIUsageMobileApp.app")
            self.assertTrue(actual.is_dir())
            self.assertNotEqual(actual, stale)

    def test_failed_command_does_not_print_or_persist_raw_secret_output(self):
        secret = "synthetic-secret-that-must-not-leak"
        with tempfile.TemporaryDirectory(prefix="ios-installer-errors-") as directory:
            result = subprocess.CompletedProcess(["xcodebuild"], 65, stdout="AI_USAGE_API_TOKEN = " + secret)
            output = io.StringIO()
            with mock.patch.object(installer.subprocess, "run", return_value=result), \
                 mock.patch.object(installer.tempfile, "tempdir", directory), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                with self.assertRaises(RuntimeError) as error:
                    installer.run(["xcodebuild", "build"])
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret, str(error.exception))
            logs = list(pathlib.Path(directory).glob("ai-usage-mobile-error-*"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn(secret, logs[0].read_text())
            self.assertIn('"exit_code": 65', logs[0].read_text())


if __name__ == "__main__":
    unittest.main()
