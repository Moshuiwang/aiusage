from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from ai_usage_widget import cli


class TestCliPusher(unittest.TestCase):
    def test_incremental_usage_ledger_since_starts_at_full_hour(self) -> None:
        now = datetime.fromisoformat("2026-07-06T16:29:05+08:00")

        since = cli._usage_ledger_since("incremental", 48, now)

        self.assertEqual(since, datetime.fromisoformat("2026-07-04T16:00:00+08:00"))

    def test_push_command_loads_device_config_and_runs_pusher(self) -> None:
        config_data = {
            "schema_version": 1,
            "source_id": "mac-local",
            "host": "macbook-pro",
            "os_user": "wangzhipeng",
            "platform": "darwin",
            "timezone": "Asia/Shanghai",
            "server_url": "http://127.0.0.1:8000/ingest",
            "timeout_seconds": 30,
            "token_env": "AI_USAGE_INGEST_TOKEN",
        }

        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config_data, handle)

            class FakePusher:
                last_config = None

                def __init__(self, config, **kwargs) -> None:
                    FakePusher.last_config = config

                def push(self) -> dict:
                    return {"success": True, "status": "accepted", "source_id": "mac-local"}

            with patch.object(cli, "DevicePusher", FakePusher):
                code = cli.main(["push", "--config", path])

            self.assertEqual(code, 0)
            self.assertIsNotNone(FakePusher.last_config)
            self.assertEqual(FakePusher.last_config.server_url, "http://127.0.0.1:8000/ingest")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_push_command_rejects_existing_lock_file(self) -> None:
        config_data = {
            "schema_version": 1,
            "source_id": "mac-local",
            "host": "macbook-pro",
            "os_user": "wangzhipeng",
            "platform": "darwin",
            "timezone": "Asia/Shanghai",
            "server_url": "http://127.0.0.1:8000/ingest",
            "timeout_seconds": 30,
            "token_env": "AI_USAGE_INGEST_TOKEN",
        }

        config_fd, config_path = tempfile.mkstemp(suffix=".json")
        lock_fd, lock_path = tempfile.mkstemp(suffix=".lock")
        try:
            with os.fdopen(config_fd, "w", encoding="utf-8") as handle:
                json.dump(config_data, handle)
            os.close(lock_fd)

            code = cli.main(["push", "--config", config_path, "--lock-file", lock_path])

            self.assertEqual(code, 1)
        finally:
            for path in [config_path, lock_path]:
                if os.path.exists(path):
                    os.remove(path)
