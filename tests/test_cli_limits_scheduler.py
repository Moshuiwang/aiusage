from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget import cli


class TestCliLimitsScheduler(unittest.TestCase):
    def test_install_limits_scheduler_dry_run_outputs_redacted_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            stdout = io.StringIO()
            with patch.dict(os.environ, {"AI_USAGE_INGEST_TOKEN": "secret-token"}), redirect_stdout(stdout):
                code = cli.main([
                    "install-limits-scheduler",
                    "--repo-dir",
                    str(base / "repo"),
                    "--limits-config",
                    str(base / "repo/config/limits.local.json"),
                    "--url",
                    "https://vpn2.chunbai.com:8443/ingest-limits",
                    "--token-env-file",
                    str(base / "state/limits-push.env"),
                    "--runner-path",
                    str(base / "bin/limits-push"),
                    "--plist-path",
                    str(base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist"),
                    "--log-dir",
                    str(base / "logs"),
                    "--dry-run",
                ])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["success"])
            self.assertTrue(payload["dry_run"])
            self.assertFalse((base / "state/limits-push.env").exists())
            self.assertNotIn("secret-token", stdout.getvalue())

    def test_install_limits_scheduler_writes_files_from_token_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo = base / "repo"
            repo.mkdir()
            stdout = io.StringIO()
            with patch.dict(os.environ, {"AI_USAGE_INGEST_TOKEN": "secret-token"}), redirect_stdout(stdout):
                code = cli.main([
                    "install-limits-scheduler",
                    "--repo-dir",
                    str(repo),
                    "--limits-config",
                    str(repo / "config/limits.local.json"),
                    "--url",
                    "https://vpn2.chunbai.com:8443/ingest-limits",
                    "--token-env-file",
                    str(base / "state/limits-push.env"),
                    "--runner-path",
                    str(base / "bin/limits-push"),
                    "--plist-path",
                    str(base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist"),
                    "--log-dir",
                    str(base / "logs"),
                ])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["success"])
            self.assertFalse(payload["dry_run"])
            self.assertTrue((base / "state/limits-push.env").exists())
            self.assertTrue((base / "bin/limits-push").exists())
            self.assertTrue((base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist").exists())
            self.assertNotIn("secret-token", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
