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
        self.assertRegex(content, r"(?m)^  workflow_dispatch:\s*$")
        self.assertNotRegex(content, r"(?m)^  push:\s*$")
        self.assertRegex(
            content,
            r"(?m)^permissions:\s*\n  contents: read\s*$",
        )
        self.assertIn(
            "group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}",
            content,
        )
        self.assertIn("cancel-in-progress: true", content)

        for job in ("changes", "python", "worker", "macos-swift", "ios-swift"):
            self.assertRegex(content, rf"(?m)^  {re.escape(job)}:\s*$")

    def test_apple_jobs_keep_required_contexts_but_use_macos_only_for_relevant_changes(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('event_name="${{ github.event_name }}"', content)
        self.assertIn('base="${{ github.event.pull_request.base.sha }}"', content)
        self.assertIn('head="${{ github.event.pull_request.head.sha }}"', content)
        self.assertIn('git diff --name-only -z "$base" "$head"', content)
        self.assertIn("clients/macos/*", content)
        self.assertIn("mobile/ios/*|tests/test_ios_xcode_integration.py", content)
        self.assertIn(".github/workflows/ci.yml|tests/test_github_actions_ci.py", content)
        self.assertNotIn("cloudflare/*)", content)
        self.assertNotIn("docs/*)", content)
        self.assertNotRegex(content, r"(?m)^\s+\*\)\s*$")
        self.assertRegex(
            content,
            r"(?ms)\.github/workflows/ci\.yml\|tests/test_github_actions_ci\.py[^\n]*\)\s*"
            r"macos=true\s*ios=true",
            "共享 CI/构建契约改动必须保守地同时运行两个苹果测试",
        )

        self.assertEqual(content.count("needs: changes"), 2)
        self.assertEqual(
            content.count("&& 'macos-15' || 'ubuntu-latest'"),
            2,
            "两个苹果必需检查都应在无关改动时降级到 Ubuntu，而不是消失或启动 macOS",
        )
        self.assertIn("name: macOS Swift", content)
        self.assertIn("name: iOS Swift", content)
        self.assertIn("Apple tests skipped by safe path scope", content)

        dispatch_block = content.split('if [ "$event_name" = "workflow_dispatch" ]; then', 1)[1]
        dispatch_block = dispatch_block.split("else", 1)[0]
        self.assertIn("macos=true", dispatch_block)
        self.assertIn("ios=true", dispatch_block)

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
