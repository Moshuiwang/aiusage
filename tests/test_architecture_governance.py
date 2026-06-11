from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestArchitectureGovernance(unittest.TestCase):
    def test_architecture_doc_records_current_owners_and_legacy_boundary(self) -> None:
        text = (ROOT / "docs" / "architecture" / "architecture.md").read_text(encoding="utf-8")
        normalized = text.casefold()

        for required in [
            "DevicePusher",
            "server_services.py",
            "snapshot_builder.py",
            "mobile_summary.py",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        for required in ["push ingest", "ssh pull", "legacy"]:
            with self.subTest(required=required):
                self.assertIn(required, normalized)

    def test_gitignore_keeps_local_runtime_artifacts_out_of_commits(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for required in [
            "/data/latest.json",
            "/data/usage.sqlite",
            "/tmp/",
            "/logs/",
            "/.build/",
            "mobile/ios/.build/",
            "mobile/ios-xcode/**/xcuserdata/",
            ".env",
            ".env.local",
            ".env.*.local",
            "*.token",
            "*.secret",
            "*.local.log",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        forbidden_exact_rules = {
            "auth*",
            ".env.*",
            "*.sqlite",
            "*.log",
            "latest.json",
            "*.xcuserstate",
        }
        ignored_lines = set(text.splitlines())
        for forbidden in forbidden_exact_rules:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, ignored_lines)

    def test_widget_configuration_sharing_design_keeps_token_boundary(self) -> None:
        text = (
            ROOT / "docs" / "architecture" / "widget-configuration-sharing.md"
        ).read_text(encoding="utf-8")
        normalized = text.casefold()

        for required in [
            "App Group",
            "Keychain access group",
            "WidgetKit",
            "MobileTokenStore",
            "AIUsageAPIBaseURL",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        for required in [
            "shared userdefaults",
            "token",
            "read-only",
            "reload timeline",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, normalized)
