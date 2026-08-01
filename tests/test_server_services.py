from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from ai_usage_widget import version_contract
from ai_usage_widget.auth import TokenAuthenticator
from ai_usage_widget.pusher import _facts_digest
from ai_usage_widget.server_services import (
    ServiceError,
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

    def test_ingest_with_optional_ccusage_daily_status_keeps_source_health_ok(self) -> None:
        payload = dict(self.valid_payload)
        payload["usage_daily"] = []
        payload["ccusage_daily_status"] = {
            "status": "missing_tool",
            "error_type": "missing_tool",
            "error_message": "ccusage not found",
        }
        payload["usage_hourly_facts"] = [
            {
                "fact_id": "codex:codex:mac-local:2026-06-01T10:00:00+08:00:2026-06-01T11:00:00+08:00:unconfirmed_local_source:openai:acct-main:mswusage_codex_token_count",
                "agent": "codex",
                "client": "codex",
                "window_start": "2026-06-01T10:00:00+08:00",
                "window_end": "2026-06-01T11:00:00+08:00",
                "ai_account": {
                    "provider": "openai",
                    "account_id": "acct-main",
                    "label": "Codex Main",
                },
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                },
                "event_count": 2,
                "session_count": 1,
                "attribution_confidence": "unconfirmed_local_source",
                "provenance": "mswusage_codex_token_count",
            }
        ]

        response = handle_ingest_payload(
            payload,
            token=self.token,
            authenticator=self.authenticator,
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
        )

        self.assertEqual(response["status"], "accepted")
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
        self.assertEqual(summary_data["summary"]["total_tokens"], 155)
        self.assertEqual(summary_data["source_status"][0]["status"], "ok")
        self.assertEqual(summary_data["source_status"][0]["error_message"], "ccusage not found")

    def test_ingest_retry_does_not_count_as_a_second_full_scan(self) -> None:
        payload = dict(self.valid_payload)
        payload["usage_daily"] = []
        payload["usage_hourly_facts"] = [
            {
                "fact_id": "codex:retry-safe-fact",
                "agent": "codex",
                "client": "codex",
                "window_start": "2026-06-01T10:00:00+08:00",
                "window_end": "2026-06-01T11:00:00+08:00",
                "ai_account": {
                    "provider": "openai",
                    "account_id": "acct-main",
                    "label": "Codex Main",
                },
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                },
                "event_count": 2,
                "session_count": 1,
                "attribution_confidence": "unconfirmed_local_source",
                "provenance": "mswusage_codex_token_count",
            }
        ]
        collector = {
            "version": "0.1.0",
            "parser_schema_version": 2,
            "mode": "full-rescan",
            "coverage": {
                "start": "2026-06-01T00:00:00+08:00",
                "end": "2026-06-02T00:00:00+08:00",
            },
            "counts": {"read_errors": 0, "unresolved_mismatch": 0},
            "scan_complete": True,
            "report_digest": "same-report-digest",
        }
        payload["usage_ledger_runs"] = [
            {
                "agent": "codex",
                "provenance": "mswusage_codex_token_count",
                "facts_digest": _facts_digest(payload["usage_hourly_facts"], collector),
                "collector": collector,
            }
        ]

        for _ in range(2):
            handle_ingest_payload(
                payload,
                token=self.token,
                authenticator=self.authenticator,
                db_path=self.db_path,
                latest_path=self.out_path,
                timezone=self.timezone,
            )

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT accuracy_status, matching_full_scans, observed_at "
                    "FROM source_accuracy WHERE source_id=? AND agent=?",
                    ("mac-local", "codex"),
                ).fetchone(),
                ("unverified", 1, payload["observed_at"]),
            )

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

    def _ingest(self, payload, **kwargs):
        return handle_ingest_payload(
            payload,
            token=self.token,
            authenticator=self.authenticator,
            db_path=self.db_path,
            latest_path=self.out_path,
            timezone=self.timezone,
            **kwargs,
        )

    def _source_report_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='source_reports'"
            ).fetchone()
            if not row or not row[0]:
                return 0
            return int(conn.execute("SELECT count(*) FROM source_reports").fetchone()[0])

    def test_ingest_reports_current_version_state_for_an_up_to_date_collector(self) -> None:
        payload = dict(self.valid_payload)
        payload["collector_release"] = {
            "collector_version": version_contract.COLLECTOR_VERSION,
            "config_schema_version": 1,
            "parser_schema_version": version_contract.COLLECTOR_PARSER_SCHEMA_VERSION,
            "release_channel": "stable",
        }

        response = self._ingest(payload)

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["version"]["state"], "current")
        self.assertEqual(response["version"]["collector_version"], version_contract.COLLECTOR_VERSION)
        self.assertEqual(
            response["version"]["min_supported_collector_version"],
            version_contract.MIN_SUPPORTED_COLLECTOR_VERSION,
        )

    def test_ingest_without_collector_release_is_accepted_but_marked_unknown(self) -> None:
        response = self._ingest(dict(self.valid_payload))

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["version"]["state"], "unknown")
        self.assertEqual(response["version"]["reason"], "collector_release_missing")
        self.assertFalse(response["version"]["verified"])
        self.assertEqual(self._source_report_count(), 1)

    def test_ingest_reports_update_available_without_rejecting_the_data(self) -> None:
        payload = dict(self.valid_payload)
        payload["collector_release"] = {"collector_version": "0.2.0"}

        response = self._ingest(
            payload,
            version_policy=version_contract.VersionPolicy(
                min_supported_collector_version="0.1.0",
                target_collector_version="0.4.0",
            ),
        )

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["version"]["state"], "update_available")
        self.assertEqual(self._source_report_count(), 1)

    def test_unsupported_collector_is_rejected_with_an_explicit_error_not_a_silent_200(self) -> None:
        payload = dict(self.valid_payload)
        payload["collector_release"] = {"collector_version": "0.1.0"}

        with self.assertRaises(ServiceError) as context:
            self._ingest(
                payload,
                version_policy=version_contract.VersionPolicy(
                    min_supported_collector_version="0.2.0",
                    target_collector_version="0.4.0",
                ),
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.error_type, version_contract.UNSUPPORTED_ERROR_TYPE)
        self.assertIn("0.1.0", context.exception.message)
        self.assertIn("0.2.0", context.exception.message)
        self.assertIn("未写入", context.exception.message)

    def test_rejected_unsupported_upload_is_not_silently_dropped_into_the_store(self) -> None:
        payload = dict(self.valid_payload)
        payload["collector_release"] = {"collector_version": "0.1.0"}

        with self.assertRaises(ServiceError):
            self._ingest(
                payload,
                version_policy=version_contract.VersionPolicy(
                    min_supported_collector_version="0.2.0",
                    target_collector_version="0.4.0",
                ),
            )

        self.assertEqual(self._source_report_count(), 0)

    def test_health_service_exposes_server_versions_and_devices_needing_attention(self) -> None:
        with open(self.out_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "source_status": [
                        {
                            "source_id": "z-old",
                            "display_name": "z-old",
                            "status": "ok",
                            "version": {"state": "update_available", "collector_version": "0.2.0"},
                        },
                        {
                            "source_id": "a-broken",
                            "display_name": "a-broken",
                            "status": "ok",
                            "version": {"state": "unsupported", "collector_version": "0.1.0"},
                        },
                        {
                            "source_id": "m-fresh",
                            "display_name": "m-fresh",
                            "status": "ok",
                            "version": {"state": "current", "collector_version": "0.3.0"},
                        },
                    ]
                },
                handle,
            )

        health = build_health_response(
            db_path=self.db_path,
            latest_path=self.out_path,
            now_provider=lambda: "2026-06-01T11:00:00+08:00",
        )

        self.assertEqual(
            set(health["versions"]["server"]),
            set(version_contract.SERVER_VERSION_FIELDS),
        )
        self.assertEqual(health["versions"]["counts"]["unsupported"], 1)
        self.assertEqual(health["versions"]["counts"]["update_available"], 1)
        self.assertEqual(health["versions"]["counts"]["current"], 1)
        self.assertEqual(
            [row["source_id"] for row in health["versions"]["needs_attention"]],
            ["a-broken", "z-old"],
        )

    def test_version_fields_never_leak_a_token_or_absolute_path_into_any_output(self) -> None:
        fake_token = "sk-ant-api03-FAKEfakeFAKEfake0123456789"
        fake_path = "/opt/ai-usage/releases/current/bin/collector"

        for value in (fake_token, fake_path):
            with self.subTest(value=value):
                payload = dict(self.valid_payload)
                payload["collector_release"] = {"collector_version": value, "build_sha": value}
                with self.assertRaises(ServiceError) as context:
                    self._ingest(payload)
                self.assertNotIn(value, context.exception.message)

        payload = dict(self.valid_payload)
        payload["collector_release"] = {
            "collector_version": version_contract.COLLECTOR_VERSION,
            "build_sha": "0a1b2c3d4e5",
        }
        response = self._ingest(payload)

        rendered = json.dumps(
            {
                "ingest": response,
                "summary": json.loads(
                    build_summary_response(
                        db_path=self.db_path,
                        latest_path=self.out_path,
                        timezone=self.timezone,
                        date_str="2026-06-01",
                        period="today",
                        machine_filter=None,
                        account_filter=None,
                    )
                ),
                "health": build_health_response(
                    db_path=self.db_path,
                    latest_path=self.out_path,
                    now_provider=lambda: "2026-06-01T11:00:00+08:00",
                ),
            },
            ensure_ascii=False,
        )

        self.assertNotIn(fake_token, rendered)
        self.assertNotIn(fake_path, rendered)
        self.assertIn(version_contract.COLLECTOR_VERSION, rendered)

    def test_summary_snapshot_lists_outdated_devices_with_deterministic_ordering(self) -> None:
        for source_id, machine, collector_version in [
            ("z-old", "linux-dev", "0.2.0"),
            ("m-current", "macbook-pro", version_contract.COLLECTOR_VERSION),
            ("a-ahead", "winbox", "0.9.0"),
        ]:
            payload = dict(self.valid_payload)
            payload["source_id"] = source_id
            payload["machine"] = machine
            payload["host"] = machine
            payload["collector_release"] = {"collector_version": collector_version}
            self._ingest(payload)

        snapshot = json.loads(
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

        by_source = {row["source_id"]: row for row in snapshot["source_status"]}
        self.assertEqual(by_source["z-old"]["version"]["state"], "update_available")
        self.assertEqual(by_source["z-old"]["version"]["collector_version"], "0.2.0")
        self.assertEqual(by_source["m-current"]["version"]["state"], "current")
        self.assertEqual(by_source["a-ahead"]["version"]["state"], "rollback_available")

        health = snapshot["version_health"]
        self.assertEqual(
            [row["source_id"] for row in health["needs_attention"]],
            ["a-ahead", "z-old"],
        )
        self.assertEqual(health["counts"]["current"], 1)
        self.assertEqual(health["counts"]["update_available"], 1)
        self.assertEqual(health["counts"]["rollback_available"], 1)
        self.assertEqual(health["server"]["target_collector_version"], version_contract.COLLECTOR_VERSION)

    def test_source_without_reported_version_shows_up_as_unknown_in_the_snapshot(self) -> None:
        self._ingest(dict(self.valid_payload))

        snapshot = json.loads(
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

        self.assertEqual(snapshot["source_status"][0]["version"]["state"], "unknown")
        self.assertEqual(
            [row["source_id"] for row in snapshot["version_health"]["needs_attention"]],
            ["mac-local"],
        )

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
