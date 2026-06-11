from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import threading
from datetime import datetime, timezone as dt_timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .auth import TokenAuthenticator
from .server_services import (
    ServiceError,
    build_health_response,
    build_mobile_summary_response,
    build_summary_response,
    handle_ingest_limits_payload,
    handle_ingest_payload,
)


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
        elif parsed_url.path == "/api/mobile/summary":
            if not self._is_authenticated():
                self.send_error_json(401, "auth_required", "Authentication required")
                return
            self.handle_get_mobile_summary(parsed_url)
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

        try:
            resp = handle_ingest_payload(
                payload,
                token=token,
                authenticator=self.server.authenticator,
                db_path=self.server.db_path,
                latest_path=self.server.latest_path,
                timezone=self.server.timezone,
            )
        except ServiceError as exc:
            self.send_error_json(exc.status_code, exc.error_type, exc.message)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

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
            response_payload = handle_ingest_limits_payload(
                payload,
                token=token,
                authenticator=self.server.authenticator,
                db_path=self.server.db_path,
                latest_path=self.server.latest_path,
                timezone=self.server.timezone,
            )
        except ServiceError as exc:
            self.send_error_json(exc.status_code, exc.error_type, exc.message)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(response_payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))

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

        try:
            snapshot_data = build_summary_response(
                db_path=self.server.db_path,
                latest_path=self.server.latest_path,
                timezone=self.server.timezone,
                date_str=date_str,
                period=period,
                machine_filter=machine,
                account_filter=account,
            )
        except Exception as exc:
            self.send_error_json(500, "internal_error", f"Failed to compile snapshot: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(snapshot_data.encode("utf-8"))

    def handle_get_mobile_summary(self, parsed_url: Any) -> None:
        query_params = parse_qs(parsed_url.query)
        date_str = query_params.get("date", [None])[0]
        period = query_params.get("period", ["today"])[0]
        machine = query_params.get("machine", [None])[0]
        account = query_params.get("account", [None])[0]

        if not date_str:
            date_str = datetime.now(dt_timezone.utc).astimezone().strftime("%Y-%m-%d")

        try:
            mobile_summary = build_mobile_summary_response(
                db_path=self.server.db_path,
                latest_path=self.server.latest_path,
                timezone=self.server.timezone,
                date_str=date_str,
                period=period,
                machine_filter=machine,
                account_filter=account,
            )
        except OSError as exc:
            self.send_error_json(500, "read_failed", f"Failed to read snapshot: {exc}")
            return
        except json.JSONDecodeError as exc:
            self.send_error_json(500, "read_failed", f"Failed to parse snapshot: {exc}")
            return
        except Exception as exc:
            self.send_error_json(500, "internal_error", f"Failed to compile snapshot: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(mobile_summary, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def handle_get_health(self) -> None:
        payload = build_health_response(db_path=self.server.db_path, latest_path=self.server.latest_path)
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
