from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_usage_widget import cli


class TestCliPusher(unittest.TestCase):
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

                def __init__(self, config) -> None:
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
