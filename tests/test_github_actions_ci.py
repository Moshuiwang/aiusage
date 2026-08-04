import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PACKAGE_JSON = ROOT / "package.json"
VERIFY_SCRIPT = ROOT / "scripts" / "verify.sh"


class TestGitHubActionsCI(unittest.TestCase):
    def test_worker_source_typecheck_is_mandatory_locally_and_in_ci(self) -> None:
        scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
        self.assertEqual(
            scripts["cf:native:typecheck"],
            "tsc --noEmit -p cloudflare/native-worker/tsconfig.src.json",
        )
        self.assertIn(
            "npm run cf:native:typecheck && npm run cf:native:test",
            scripts["cf:native:verify"],
        )
        self.assertTrue(
            "npm run cf:native:verify" in VERIFY_SCRIPT.read_text(encoding="utf-8"),
            "scripts/verify.sh must run the typecheck-and-test Worker gate",
        )
        self.assertIn(
            "npm run cf:native:typecheck",
            WORKFLOW.read_text(encoding="utf-8"),
        )

    def test_worker_job_uses_an_npm_lockfile(self) -> None:
        self.assertTrue(
            (ROOT / "package-lock.json").is_file(),
            "npm ci requires package-lock.json",
        )
        npm_config = ROOT / ".npmrc"
        self.assertTrue(npm_config.is_file(), "missing npm peer-resolution config")
        self.assertIn(
            "legacy-peer-deps=true",
            npm_config.read_text(encoding="utf-8"),
        )

    def test_ci_workflow_has_approved_triggers_permissions_and_jobs(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), "missing .github/workflows/ci.yml")

        content = WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(content, r"(?m)^  pull_request:\s*$")
        self.assertRegex(
            content,
            r"(?m)^  push:\s*\n    branches:\s*\n      - main\s*$",
        )
        self.assertRegex(
            content,
            r"(?m)^permissions:\s*\n  contents: read\s*$",
        )
        self.assertIn("cancel-in-progress: true", content)

        for job in ("python", "worker", "macos-swift", "ios-swift"):
            self.assertRegex(content, rf"(?m)^  {re.escape(job)}:\s*$")

    def test_ci_workflow_runs_the_approved_commands_without_production_access(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), "missing .github/workflows/ci.yml")

        content = WORKFLOW.read_text(encoding="utf-8")
        commands = (
            "PYTHONPATH=src python3 -m unittest discover -s tests -v",
            "npm ci",
            "npm run cf:native:typecheck",
            "npm run cf:native:test",
            "swift test --package-path clients/macos",
            "swift test --package-path mobile/ios",
            "python3 -m unittest tests.test_ios_xcode_integration -v",
        )
        for command in commands:
            self.assertIn(command, content)

        forbidden = (
            "${{ secrets.",
            "aiusage.chunbai.com",
            "continue-on-error",
        )
        for value in forbidden:
            self.assertNotIn(value, content)


if __name__ == "__main__":
    unittest.main()
