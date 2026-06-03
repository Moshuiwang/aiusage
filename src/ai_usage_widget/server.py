from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import threading
from datetime import datetime, timezone as dt_timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .auth import TokenAuthenticator
from .config import ConfigError
from .ingest import IngestValidationError, validate_ingest_payload, IngestResponse
from .limits import LimitContractError, parse_limit_window
from .normalize import normalize_ingest_block_request, normalize_ingest_hourly_request, normalize_ingest_request
from .storage_sqlite import write_limit_windows, write_sqlite
from .snapshot_builder import build_snapshot


class IngestAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/ingest":
            self.handle_ingest()
        elif parsed_url.path == "/ingest-limits":
            self.handle_ingest_limits()
        elif parsed_url.path == "/login":
            self.handle_login()
        else:
            self.send_error_json(404, "not_found", "Endpoint not found")

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/summary":
            if not self._is_authenticated():
                self.send_error_json(401, "auth_required", "Authentication required")
                return
            self.handle_get_summary(parsed_url)
        elif parsed_url.path == "/api/health":
            if not self._is_authenticated():
                self.send_error_json(401, "auth_required", "Authentication required")
                return
            self.handle_get_health()
        elif parsed_url.path in {"/", "/dashboard"}:
            if not self._is_authenticated():
                self.send_login_page()
                return
            self.handle_get_dashboard()
        elif parsed_url.path == "/login":
            self.send_login_page()
        elif parsed_url.path.startswith("/static/"):
            if not self._is_authenticated():
                self.send_error_json(401, "auth_required", "Authentication required")
                return
            self.handle_get_static_asset(parsed_url.path)
        else:
            self.send_error_json(404, "not_found", "Endpoint not found")

    def handle_login(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        token = ""
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                payload = json.loads(body.decode("utf-8"))
                token = str(payload.get("token", ""))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_login_page(status_code=400, message="Invalid login payload")
                return
        else:
            parsed = parse_qs(body.decode("utf-8"))
            token = parsed.get("token", [""])[0]

        if not self.server.authenticator.verify(token):
            self.send_login_page(status_code=401, message="Invalid token")
            return

        self.send_response(303)
        self.send_header("Location", "/dashboard")
        self.send_header("Set-Cookie", self._session_cookie_header())
        self._send_security_headers()
        self.end_headers()

    def handle_ingest(self) -> None:
        # 1. 提取 Authorization Token
        auth_header = self.headers.get("Authorization", "")
        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        # 2. 读取 Body 字节
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error_json(400, "http_schema_invalid", "Missing payload body")
            return

        body = self.rfile.read(content_length)

        # 3. 解析 JSON
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self.send_error_json(400, "http_schema_invalid", f"Malformed JSON: {exc}")
            return

        # 4. 执行契约校验
        try:
            req = validate_ingest_payload(
                payload,
                token=token,
                authenticator=self.server.authenticator,
            )
        except IngestValidationError as exc:
            status_code = 401 if exc.error_type == "http_auth_failed" else 400
            self.send_error_json(status_code, exc.error_type, str(exc))
            return
        except Exception as exc:
            self.send_error_json(500, "internal_error", str(exc))
            return

        # 5. 校验通过，正常化为 UsageItems 列表
        items = normalize_ingest_request(req)
        hourly_items = normalize_ingest_hourly_request(req)
        block_items = normalize_ingest_block_request(req)

        # 6. 构造元数据并写入 SQLite Store
        collected_at = datetime.now(dt_timezone.utc).astimezone().isoformat()
        report = {
            "source_id": req.source_id,
            "report_type": "daily",
            "command": "HTTP Ingest",
            "status": req.collection_status,
            "ccusage_version": None,
            "first_period": None,
            "last_period": None,
            "error_type": req.error_type,
            "error_message": req.error_message,
        }
        periods = [item.date for item in items]
        if periods:
            report["first_period"] = min(periods)
            report["last_period"] = max(periods)

        try:
            write_sqlite(
                path=self.server.db_path,
                collected_at=collected_at,
                timezone=self.server.timezone,
                run_status="ok",
                source_reports=[report],
                items=items,
                hourly_items=hourly_items,
                block_items=block_items,
                source_identities=[{
                    "source_id": req.source_id,
                    "host": req.host,
                    "machine": req.machine or req.host,
                    "os_user": req.os_user,
                    "platform": req.platform,
                }],
            )
        except Exception as exc:
            self.send_error_json(500, "write_failed", f"Failed to save data: {exc}")
            return

        # 7. 写入数据库后，联动触发 build_snapshot 重建最新快照
        today_str = datetime.now(dt_timezone.utc).astimezone().strftime("%Y-%m-%d")
        try:
            build_snapshot(
                db_path=self.server.db_path,
                output_path=self.server.latest_path,
                date_str=today_str,
                timezone_str=self.server.timezone,
            )
        except Exception as exc:
            # 记录异常，但不阻塞 200 响应
            print(f"Failed to build snapshot during ingest: {exc}")

        # 8. 返回成功响应
        resp = IngestResponse(
            status="accepted",
            source_id=req.source_id,
            accepted_at=collected_at,
            message="Data accepted successfully",
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(resp.to_dict(), ensure_ascii=False).encode("utf-8"))

    def handle_ingest_limits(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not self.server.authenticator.verify(token):
            self.send_error_json(401, "http_auth_failed", "Invalid or missing token")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error_json(400, "limit_schema_invalid", "Missing payload body")
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_error_json(400, "limit_schema_invalid", f"Malformed JSON: {exc}")
            return

        try:
            observed_at, windows = _validate_limits_ingest_payload(payload)
        except LimitContractError as exc:
            self.send_error_json(400, exc.error_type, str(exc))
            return

        try:
            write_limit_windows(self.server.db_path, windows, seen_at=observed_at)
        except Exception as exc:
            self.send_error_json(500, "write_failed", f"Failed to save limits: {exc}")
            return

        try:
            build_snapshot(
                db_path=self.server.db_path,
                output_path=self.server.latest_path,
                date_str=observed_at[:10],
                timezone_str=self.server.timezone,
                current_time_str=observed_at,
            )
        except Exception as exc:
            print(f"Failed to build snapshot during limits ingest: {exc}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": True,
            "status": "accepted",
            "windows_written": len(windows),
            "accepted_at": observed_at,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def handle_get_summary(self, parsed_url: Any) -> None:
        # 1. 提取日期查询参数
        query_params = parse_qs(parsed_url.query)
        date_str = query_params.get("date", [None])[0]
        period = query_params.get("period", ["today"])[0]
        machine = query_params.get("machine", [None])[0]
        account = query_params.get("account", [None])[0]

        if not date_str:
            # 默认取配置时区的当前日期
            date_str = datetime.now(dt_timezone.utc).astimezone().strftime("%Y-%m-%d")

        # 2. 动态触发一次最新快照重构
        try:
            build_snapshot(
                db_path=self.server.db_path,
                output_path=self.server.latest_path,
                date_str=date_str,
                timezone_str=self.server.timezone,
                period=period,
                machine_filter=machine,
                account_filter=account,
            )
        except Exception as exc:
            self.send_error_json(500, "internal_error", f"Failed to compile snapshot: {exc}")
            return

        # 3. 读取并回传最新快照 JSON 文件
        if not os.path.exists(self.server.latest_path):
            self.send_error_json(404, "not_found", "No snapshot available")
            return

        try:
            with open(self.server.latest_path, "r", encoding="utf-8") as f:
                snapshot_data = f.read()
        except OSError as exc:
            self.send_error_json(500, "read_failed", f"Failed to read snapshot: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(snapshot_data.encode("utf-8"))

    def handle_get_health(self) -> None:
        latest_data: Dict[str, Any] = {}
        if os.path.exists(self.server.latest_path):
            try:
                with open(self.server.latest_path, "r", encoding="utf-8") as f:
                    latest_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                latest_data = {}

        source_status = latest_data.get("source_status") if isinstance(latest_data, dict) else []
        if not isinstance(source_status, list):
            source_status = []
        counts: Dict[str, int] = {}
        for source in source_status:
            if not isinstance(source, dict):
                continue
            status = str(source.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1

        db_size = os.path.getsize(self.server.db_path) if os.path.exists(self.server.db_path) else 0
        latest_mtime = (
            datetime.fromtimestamp(os.path.getmtime(self.server.latest_path), dt_timezone.utc).astimezone().isoformat()
            if os.path.exists(self.server.latest_path)
            else None
        )
        payload = {
            "status": "ok",
            "generated_at": datetime.now(dt_timezone.utc).astimezone().isoformat(),
            "database": {
                "path": self.server.db_path,
                "size_bytes": db_size,
                "exists": os.path.exists(self.server.db_path),
            },
            "snapshot": {
                "path": self.server.latest_path,
                "exists": os.path.exists(self.server.latest_path),
                "updated_at": latest_mtime,
            },
            "source_status": {
                "total": len(source_status),
                "counts": counts,
                "non_ok": [
                    {
                        "source_id": str(source.get("source_id") or ""),
                        "status": str(source.get("status") or "unknown"),
                    }
                    for source in source_status
                    if isinstance(source, dict) and str(source.get("status") or "unknown") != "ok"
                ],
            },
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def handle_get_dashboard(self) -> None:
        """返回 Web Dashboard 静态页面"""
        self._send_static_file("index.html", "text/html; charset=utf-8")

    def handle_get_static_asset(self, path: str) -> None:
        asset_name = path.removeprefix("/static/")
        content_types = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".html": "text/html; charset=utf-8",
        }
        _, ext = os.path.splitext(asset_name)
        content_type = content_types.get(ext, "application/octet-stream")
        self._send_static_file(asset_name, content_type)

    def _send_static_file(self, asset_name: str, content_type: str) -> None:
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        normalized = os.path.normpath(asset_name)
        if normalized.startswith("..") or os.path.isabs(normalized):
            self.send_error_json(404, "not_found", "Static asset not found")
            return

        asset_path = os.path.join(static_dir, normalized)
        if not os.path.exists(asset_path) or not os.path.isfile(asset_path):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(b"Static asset not found")
            return

        try:
            with open(asset_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(content)
        except OSError as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(f"Failed to load static asset: {exc}".encode("utf-8"))

    def send_login_page(self, status_code: int = 200, message: str = "") -> None:
        escaped_message = html.escape(message)
        error_block = f"<p class=\"error\">{escaped_message}</p>" if escaped_message else ""
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        login_path = os.path.join(static_dir, "login.html")
        try:
            with open(login_path, "r", encoding="utf-8") as f:
                content = f.read().replace("{{ERROR_BLOCK}}", error_block)
        except OSError:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(b"Login HTML template not found")
            return
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def send_error_json(self, status_code: int, error_type: str, message: str) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        resp = {
            "status": "error",
            "error_type": error_type,
            "message": message,
        }
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

    def _is_authenticated(self) -> bool:
        authenticator = self.server.authenticator
        if not authenticator.is_required:
            return True

        auth_header = self.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            supplied = auth_header[7:].strip()
            if authenticator.verify(supplied):
                return True

        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name == "ai_usage_session":
                return hmac.compare_digest(value, self._session_cookie_value())
        return False

    def _session_cookie_value(self) -> str:
        token = self.server.authenticator.session_secret
        return hmac.new(
            token.encode("utf-8"),
            b"ai-usage-dashboard-session-v1",
            hashlib.sha256,
        ).hexdigest()

    def _session_cookie_header(self) -> str:
        return (
            "ai_usage_session="
            + self._session_cookie_value()
            + "; Max-Age=2592000; Path=/; HttpOnly; Secure; SameSite=Lax"
        )

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")


class ThreadedHTTPServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: Any,
        db_path: str,
        latest_path: str,
        token: Optional[str],
        timezone: str,
        token_specs: Optional[str] = None,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.db_path = db_path
        self.latest_path = latest_path
        self.token = token
        self.authenticator = TokenAuthenticator.from_values(token, token_specs)
        self.timezone = timezone


def _validate_limits_ingest_payload(payload: Any):
    if not isinstance(payload, dict):
        raise LimitContractError("limit_schema_invalid", "limits payload must be an object")
    _reject_sensitive_payload_keys(payload)

    if payload.get("schema_version") != 1:
        raise LimitContractError("limit_schema_invalid", "schema_version must be 1")
    observed_at = payload.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise LimitContractError("limit_schema_invalid", "observed_at must be a non-empty string")
    observed_at = observed_at.strip()
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LimitContractError("limit_schema_invalid", "observed_at must be an ISO 8601 datetime") from exc

    windows_payload = payload.get("windows")
    if not isinstance(windows_payload, list):
        raise LimitContractError("limit_schema_invalid", "windows must be a list")
    windows = []
    for item in windows_payload:
        if not isinstance(item, dict):
            raise LimitContractError("limit_schema_invalid", "limit window must be an object")
        _reject_sensitive_payload_keys(item)
        windows.append(parse_limit_window(item))
    return observed_at, windows


def _reject_sensitive_payload_keys(payload: Dict[str, Any]) -> None:
    sensitive_keys = {"token", "auth_file", "api_key", "secret", "env", "raw_json", "raw"}
    present = sorted(key for key in payload if key in sensitive_keys)
    if present:
        raise LimitContractError("limit_schema_invalid", "sensitive fields are not accepted: " + ", ".join(present))


def start_test_server(
    host: str,
    port: int,
    db_path: str,
    latest_path: str,
    token: Optional[str] = None,
    token_specs: Optional[str] = None,
    timezone: str = "Asia/Shanghai",
) -> tuple[threading.Thread, ThreadedHTTPServer]:
    """启动本地轻量测试服务器并跑在后台线程中"""
    httpd = ThreadedHTTPServer(
        (host, port),
        IngestAPIHandler,
        db_path=db_path,
        latest_path=latest_path,
        token=token,
        token_specs=token_specs,
        timezone=timezone,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return thread, httpd


def run_server(
    host: str,
    port: int,
    db_path: str,
    latest_path: str,
    token: Optional[str] = None,
    token_specs: Optional[str] = None,
    timezone: str = "Asia/Shanghai",
) -> None:
    """启动 HTTP Ingest 与 Web API 服务进程 (阻塞主线程)"""
    httpd = ThreadedHTTPServer(
        (host, port),
        IngestAPIHandler,
        db_path=db_path,
        latest_path=latest_path,
        token=token,
        token_specs=token_specs,
        timezone=timezone,
    )
    print(f"Starting AI Usage server on {host}:{port} with timezone={timezone} ...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()
