from __future__ import annotations

import json
import os
import tempfile
import unittest

from ai_usage_widget.auth import TokenAuthenticator
from ai_usage_widget.server_services import (
    build_health_response,
    build_mobile_summary_response,
    build_summary_response,
    handle_ingest_payload,
    handle_ingest_limits_payload,
)


class TestServerServices(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.out_fd, self.out_path = tempfile.mkstemp(suffix=".json")
        self.timezone = "Asia/Shanghai"
        self.token = "admin-secret-token"
        self.authenticator = TokenAuthenticator.from_values(self.token)
        self.valid_payload = {
            "schema_version": 1,
            "source_id": "mac-local",
            "host": "macbook-pro",
            "machine": "macbook-pro",
            "os_user": "wangzhipeng",
            "platform": "darwin",
            "timezone": self.timezone,
            "observed_at": "2026-06-01T10:40:00+08:00",
            "collection_window": "daily",
            "usage_daily": [
                {
                    "agent": "claude",
                    "period": "2026-06-01",
                    "inputTokens": 1200,
                    "outputTokens": 800,
                    "totalTokens": 2000,
                }
            ],
        }

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.close(self.out_fd)
        for path in [self.db_path, self.out_path]:
            if os.path.exists(path):
                os.remove(path)

    def test_ingest_service_preserves_summary_contract(self) -> None:
        response = handle_ingest_payload(
            self.valid_payload,
            token=self.token,
            authenticator=self.authenticator,
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
        )

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["source_id"], "mac-local")

        summary_data = json.loads(
            build_summary_response(
                db_path=self.db_path,
                latest_path=self.out_path,
                timezone=self.timezone,
                date_str="2026-06-01",
                period="today",
                machine_filter=None,
                account_filter=None,
            )
        )
        self.assertEqual(summary_data["summary"]["total_tokens"], 2000)
        self.assertEqual(summary_data["source_status"][0]["status"], "ok")

    def test_mobile_summary_service_reuses_summary_snapshot(self) -> None:
        handle_ingest_payload(
            self.valid_payload,
            token=self.token,
            authenticator=self.authenticator,
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
        )

        mobile_summary = build_mobile_summary_response(
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
            date_str="2026-06-01",
            period="today",
            machine_filter=None,
            account_filter=None,
        )

        self.assertEqual(mobile_summary["client"], "ios")
        self.assertEqual(mobile_summary["period"]["total_tokens"], 2000)
        self.assertEqual(mobile_summary["sources"][0]["source_id"], "mac-local")

    def test_health_service_reads_existing_snapshot_without_rebuilding(self) -> None:
        with open(self.out_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "source_status": [
                        {"source_id": "mac-local", "status": "ok"},
                        {"source_id": "linux-dev", "status": "stale"},
                    ]
                },
                handle,
            )

        health = build_health_response(
            db_path=self.db_path,
            latest_path=self.out_path,
            now_provider=lambda: "2026-06-01T11:00:00+08:00",
        )

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["generated_at"], "2026-06-01T11:00:00+08:00")
        self.assertEqual(health["source_status"]["counts"], {"ok": 1, "stale": 1})
        self.assertEqual(health["source_status"]["non_ok"], [{"source_id": "linux-dev", "status": "stale"}])

    def test_limits_ingest_service_preserves_response_shape(self) -> None:
        response = handle_ingest_limits_payload(
            {
                "schema_version": 1,
                "observed_at": "2026-06-01T10:45:00+08:00",
                "windows": [
                    {
                        "source_id": "codex-main",
                        "provider": "codex",
                        "window": "session",
                        "used_percent": 40,
                        "remaining_percent": 60,
                        "reset_at": "2026-06-01T15:45:00+08:00",
                        "window_duration_minutes": 300,
                        "observed_at": "2026-06-01T10:45:00+08:00",
                        "source_type": "runtime_api",
                        "confidence": "observed",
                        "status": "ok",
                    }
                ],
            },
            token=self.token,
            authenticator=self.authenticator,
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
        )

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["windows_written"], 1)
        self.assertEqual(response["accepted_at"], "2026-06-01T10:45:00+08:00")
