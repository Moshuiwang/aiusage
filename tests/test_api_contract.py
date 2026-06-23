from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from typing import Any, Optional

from ai_usage_widget.server import start_test_server


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "contract")
GOLDEN_PATH = os.path.join(FIXTURE_DIR, "api_contract_golden.json")

VOLATILE_FIELDS = {
    "accepted_at",
    "generated_at",
    "mtime",
    "path",
    "size_bytes",
    "updated_at",
}
ENUM_FIELDS = {
    "client",
    "confidence",
    "error_type",
    "exists",
    "granularity",
    "id",
    "official",
    "period",
    "provider",
    "schema_version",
    "status",
    "success",
    "window",
}
SENSITIVE_SUBSTRINGS = (
    "contract-test-token",
    "/Users/",
    "/private/",
    "/tmp/",
    ".claude",
    ".codex",
    "BEGIN OPENSSH",
)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TestAPIContractGolden(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "contract.sqlite")
        self.latest_path = os.path.join(self.temp_dir.name, "latest.json")
        self.token = "contract-test-token"
        self.timezone = "Asia/Shanghai"

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()

        self.server_thread, self.httpd = start_test_server(
            host="127.0.0.1",
            port=self.port,
            db_path=self.db_path,
            latest_path=self.latest_path,
            token=self.token,
            timezone=self.timezone,
        )
        time.sleep(0.2)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.server_thread.join()
        self.httpd.server_close()
        self.temp_dir.cleanup()

    def test_current_api_contract_matches_golden(self) -> None:
        records = self._collect_contract_records()
        if os.environ.get("UPDATE_API_CONTRACT_GOLDEN") == "1":
            os.makedirs(FIXTURE_DIR, exist_ok=True)
            with open(GOLDEN_PATH, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")

        with open(GOLDEN_PATH, "r", encoding="utf-8") as handle:
            expected = json.load(handle)

        self.assertEqual(records, expected)

    def test_contract_golden_contains_no_sensitive_runtime_data(self) -> None:
        with open(GOLDEN_PATH, "r", encoding="utf-8") as handle:
            raw = handle.read()

        for value in SENSITIVE_SUBSTRINGS:
            with self.subTest(value=value):
                self.assertNotIn(value, raw)

    def _collect_contract_records(self) -> list[dict[str, Any]]:
        records = [
            self._record("root-login-page", "GET", "/", auth=False),
            self._record("login-page", "GET", "/login", auth=False),
            self._record("static-css-requires-auth", "GET", "/static/dashboard.css", auth=False),
            self._record("static-css-authorized", "GET", "/static/dashboard.css", auth=True),
            self._record("static-missing-authorized", "GET", "/static/missing.css", auth=True),
            self._record(
                "login-invalid-token",
                "POST",
                "/login",
                data={"token": "wrong"},
                auth=False,
                content_type="application/x-www-form-urlencoded",
            ),
            self._record(
                "login-valid-redirect",
                "POST",
                "/login",
                data={"token": self.token},
                auth=False,
                content_type="application/x-www-form-urlencoded",
                follow_redirects=False,
            ),
            self._record("summary-requires-auth", "GET", "/api/summary?date=2026-06-03", auth=False),
            self._record("mobile-summary-requires-auth", "GET", "/api/mobile/summary?date=2026-06-03", auth=False),
            self._record("health-requires-auth", "GET", "/api/health", auth=False),
            self._record("ingest-auth-failed", "POST", "/ingest", data=self._usage_payload_one(), auth_token="wrong"),
            self._record(
                "ingest-schema-invalid",
                "POST",
                "/ingest",
                data={"schema_version": 1, "source_id": "broken"},
                auth=True,
            ),
            self._record("ingest-success-day1", "POST", "/ingest", data=self._usage_payload_one(), auth=True),
            self._record("ingest-idempotent-duplicate-day1", "POST", "/ingest", data=self._usage_payload_one(), auth=True),
            self._record("ingest-success-day2", "POST", "/ingest", data=self._usage_payload_two(), auth=True),
            self._record("ingest-success-day3", "POST", "/ingest", data=self._usage_payload_three(), auth=True),
        ]

        for period in ("today", "week", "month", "all"):
            records.append(
                self._record(
                    f"summary-{period}-missing-limits",
                    "GET",
                    f"/api/summary?date=2026-06-03&period={period}",
                    auth=True,
                )
            )
            records.append(
                self._record(
                    f"mobile-summary-{period}-missing-limits",
                    "GET",
                    f"/api/mobile/summary?date=2026-06-03&period={period}",
                    auth=True,
                )
            )

        records.extend(
            [
                self._record(
                    "summary-week-machine-filter",
                    "GET",
                    "/api/summary?date=2026-06-03&period=week&machine=macbook-pro",
                    auth=True,
                ),
                self._record(
                    "summary-week-account-filter",
                    "GET",
                    "/api/summary?date=2026-06-03&period=week&account=alice",
                    auth=True,
                ),
                self._record(
                    "mobile-summary-week-machine-filter",
                    "GET",
                    "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev",
                    auth=True,
                ),
                self._record(
                    "mobile-summary-week-account-filter",
                    "GET",
                    "/api/mobile/summary?date=2026-06-03&period=week&account=bob",
                    auth=True,
                ),
                self._record("health-before-limits", "GET", "/api/health", auth=True),
                self._record("ingest-limits-requires-auth", "POST", "/ingest-limits", data=self._limits_payload(), auth=False),
                self._record(
                    "ingest-limits-schema-invalid",
                    "POST",
                    "/ingest-limits",
                    data={"schema_version": 1, "windows": []},
                    auth=True,
                ),
                self._record("ingest-limits-success-observed", "POST", "/ingest-limits", data=self._limits_payload(), auth=True),
                self._record(
                    "summary-week-observed-limits",
                    "GET",
                    "/api/summary?date=2026-06-03&period=week",
                    auth=True,
                ),
                self._record(
                    "mobile-summary-week-observed-limits",
                    "GET",
                    "/api/mobile/summary?date=2026-06-03&period=week",
                    auth=True,
                ),
                self._record("health-after-limits", "GET", "/api/health", auth=True),
            ]
        )
        return records

    def _record(
        self,
        name: str,
        method: str,
        path: str,
        *,
        data: Optional[dict[str, Any]] = None,
        auth: bool = False,
        auth_token: Optional[str] = None,
        content_type: str = "application/json",
        follow_redirects: bool = True,
    ) -> dict[str, Any]:
        status, headers, body = self._request(
            method,
            path,
            data=data,
            auth=auth,
            auth_token=auth_token,
            content_type=content_type,
            follow_redirects=follow_redirects,
        )
        content_type_header = headers.get("Content-Type", "")
        return {
            "name": name,
            "request": {
                "method": method,
                "path": path,
                "auth": bool(auth or auth_token),
            },
            "response": {
                "status": status,
                "content_type": content_type_header.split(";")[0],
                "location": headers.get("Location") if "Location" in headers else None,
                "body": self._body_contract(content_type_header, body),
            },
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[dict[str, Any]],
        auth: bool,
        auth_token: Optional[str],
        content_type: str,
        follow_redirects: bool,
    ) -> tuple[int, Any, bytes]:
        headers = {}
        if auth or auth_token:
            headers["Authorization"] = f"Bearer {auth_token or self.token}"

        body = None
        if data is not None:
            if content_type == "application/json":
                body = json.dumps(data, sort_keys=True).encode("utf-8")
            else:
                body = f"token={data.get('token', '')}".encode("utf-8")
            headers["Content-Type"] = content_type

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        opener = urllib.request.build_opener(NoRedirectHandler()) if not follow_redirects else urllib.request.build_opener()
        try:
            with opener.open(req) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def _body_contract(self, content_type: str, body: bytes) -> dict[str, Any]:
        if "application/json" in content_type:
            payload = json.loads(body.decode("utf-8"))
            return {"kind": "json", "shape": self._shape(payload)}
        if "text/html" in content_type:
            return {"kind": "html", "present": bool(body)}
        if body:
            return {"kind": "text", "present": True}
        return {"kind": "empty", "present": False}

    def _shape(self, value: Any, field_name: str = "") -> dict[str, Any]:
        if field_name in VOLATILE_FIELDS or field_name.endswith("_path"):
            return {"type": type(value).__name__, "value": "<masked>"}
        if isinstance(value, dict):
            return {
                "type": "object",
                "keys": sorted(value.keys()),
                "fields": {key: self._shape(value[key], key) for key in sorted(value.keys())},
            }
        if isinstance(value, list):
            item_shapes = [self._shape(item) for item in value]
            return {
                "type": "array",
                "length": len(value),
                "items": self._unique_shapes(item_shapes),
            }
        value_type = "null" if value is None else type(value).__name__
        if field_name in ENUM_FIELDS:
            return {"type": value_type, "value": value}
        return {"type": value_type}

    def _unique_shapes(self, shapes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        unique = []
        for shape in shapes:
            serialized = json.dumps(shape, sort_keys=True)
            if serialized in seen:
                continue
            seen.add(serialized)
            unique.append(shape)
        return unique

    def _usage_payload_one(self) -> dict[str, Any]:
        return self._usage_payload(
            source_id="mac-local",
            host="macbook-pro",
            machine="macbook-pro",
            os_user="alice",
            platform="darwin",
            agent="claude",
            period="2026-06-01",
            model="claude-sonnet",
            input_tokens=1200,
            output_tokens=500,
            cache_tokens=300,
        )

    def _usage_payload_two(self) -> dict[str, Any]:
        return self._usage_payload(
            source_id="linux-dev-bob",
            host="linux-dev",
            machine="linux-dev",
            os_user="bob",
            platform="linux",
            agent="codex",
            period="2026-06-02",
            model="gpt-5",
            input_tokens=1600,
            output_tokens=900,
            cache_tokens=500,
        )

    def _usage_payload_three(self) -> dict[str, Any]:
        return self._usage_payload(
            source_id="mac-local",
            host="macbook-pro",
            machine="macbook-pro",
            os_user="alice",
            platform="darwin",
            agent="claude",
            period="2026-06-03",
            model="claude-sonnet",
            input_tokens=2200,
            output_tokens=600,
            cache_tokens=200,
        )

    def _usage_payload(
        self,
        *,
        source_id: str,
        host: str,
        machine: str,
        os_user: str,
        platform: str,
        agent: str,
        period: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_id": source_id,
            "host": host,
            "machine": machine,
            "os_user": os_user,
            "platform": platform,
            "timezone": self.timezone,
            "observed_at": f"{period}T10:40:00+08:00",
            "collection_window": "daily",
            "usage_daily": [
                {
                    "agent": agent,
                    "period": period,
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "cacheCreationTokens": cache_tokens,
                    "cacheReadTokens": 0,
                    "totalTokens": input_tokens + output_tokens + cache_tokens,
                    "modelBreakdowns": [
                        {
                            "modelName": model,
                            "inputTokens": input_tokens,
                            "outputTokens": output_tokens,
                            "cacheCreationTokens": cache_tokens,
                            "cacheReadTokens": 0,
                            "totalTokens": input_tokens + output_tokens + cache_tokens,
                        }
                    ],
                }
            ],
        }

    def _limits_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "observed_at": "2026-06-03T11:00:00+08:00",
            "windows": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 40,
                    "remaining_percent": 60,
                    "reset_at": "2026-06-03T16:00:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-03T11:00:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                },
                {
                    "source_id": "claude-weekly",
                    "provider": "claude",
                    "window": "week",
                    "used_percent": 0,
                    "remaining_percent": 0,
                    "reset_at": "2026-06-10T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-03T11:00:00+08:00",
                    "source_type": "oauth_usage_api",
                    "confidence": "missing",
                    "status": "provider_failed",
                },
            ],
        }
