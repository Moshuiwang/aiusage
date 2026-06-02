from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone as dt_timezone
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, Optional, Tuple

from .config import DeviceConfig
from .models import CommandResult


class IngestHTTPClient:
    """Ingest API 的 HTTP 客户端基类，默认使用 Python 标准库 urllib.request 实现"""
    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        req_data = json.dumps(data).encode("utf-8")
        req_headers = headers.copy()
        req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=req_data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                return response.status, resp_data
        except urllib.error.HTTPError as e:
            try:
                resp_data = json.loads(e.read().decode("utf-8"))
            except Exception:
                resp_data = {}
            return e.code, resp_data
        except Exception as e:
            raise e


def default_executor(argv: list[str], timeout: float) -> CommandResult:
    """默认的命令行执行器，利用 subprocess.run 执行"""
    start = time.monotonic()
    display_command = " ".join(argv)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            duration_ms=int((time.monotonic() - start) * 1000),
            error_type="missing_tool",
            error_message=str(exc),
            command=display_command,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            duration_ms=int((time.monotonic() - start) * 1000),
            error_type="timeout",
            error_message=f"command timed out after {timeout:g}s",
            command=display_command,
        )

    error_type = None
    error_message = None
    if completed.returncode != 0:
        error_type = "command_failed"
        error_message = f"command exited with code {completed.returncode}"

    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        duration_ms=int((time.monotonic() - start) * 1000),
        error_type=error_type,
        error_message=error_message,
        command=display_command,
    )


class DevicePusher:
    def __init__(
        self,
        config: DeviceConfig,
        executor: Callable[[list[str], float], CommandResult] = default_executor,
        http_client: IngestHTTPClient = IngestHTTPClient(),
    ) -> None:
        self.config = config
        self.executor = executor
        self.http_client = http_client

    def push(self) -> Dict[str, Any]:
        """
        执行本地采集并主动将 daily usage payload 推送至 HTTP Ingest Server
        """
        # 1. 采集 ccusage 报告
        # ccusage daily --json --timezone <config.timezone>
        argv = ["ccusage", "daily", "--json", "--timezone", self.config.timezone]
        res = self.executor(argv, float(self.config.timeout_seconds))

        if not res.ok:
            return self._push_source_status(
                status=res.error_type or "command_failed",
                error_type=res.error_type or "command_failed",
                error_message=res.error_message or "ccusage command failed",
            )

        # 2. 解析 ccusage 的数据并规范化 (TP-V2-006)
        try:
            ccusage_data = json.loads(res.stdout) if res.stdout else {}
            if not isinstance(ccusage_data, dict):
                return {
                    "success": False,
                    "error_type": "unsupported_shape",
                    "error_message": "ccusage JSON must be an object",
                }
            raw_daily = ccusage_data.get("daily", [])
            if not isinstance(raw_daily, list):
                raw_daily = []
            usage_daily = []
            for row in raw_daily:
                if isinstance(row, dict):
                    normalized_row = row.copy()
                    if not normalized_row.get("agent"):
                        normalized_row["agent"] = "unknown"
                    usage_daily.append(normalized_row)
        except json.JSONDecodeError as exc:
            return {
                "success": False,
                "error_type": "invalid_json",
                "error_message": f"Failed to decode ccusage JSON: {exc}",
            }

        ccusage_session_report = None
        session_argv = ["ccusage", "session", "--json", "--timezone", self.config.timezone]
        session_res = self.executor(session_argv, float(self.config.timeout_seconds))
        if session_res.ok and session_res.stdout:
            try:
                session_data = json.loads(session_res.stdout)
                if isinstance(session_data, dict) and isinstance(session_data.get("session"), list):
                    ccusage_session_report = session_data
            except json.JSONDecodeError:
                ccusage_session_report = None

        ccusage_blocks_report = None
        blocks_argv = ["ccusage", "blocks", "--json", "--timezone", self.config.timezone]
        blocks_res = self.executor(blocks_argv, float(self.config.timeout_seconds))
        if blocks_res.ok and blocks_res.stdout:
            try:
                blocks_data = json.loads(blocks_res.stdout)
                if isinstance(blocks_data, dict) and isinstance(blocks_data.get("blocks"), list):
                    ccusage_blocks_report = blocks_data
            except json.JSONDecodeError:
                ccusage_blocks_report = None

        # 3. 组织 Ingest Payload
        # ISO 8601 格式的 observed_at 时间戳
        observed_at = datetime.now(dt_timezone.utc).astimezone().isoformat()
        payload = {
            "schema_version": self.config.schema_version,
            "source_id": self.config.source_id,
            "host": self.config.host,
            "machine": self.config.machine,
            "os_user": self.config.os_user,
            "platform": self.config.platform,
            "timezone": self.config.timezone,
            "observed_at": observed_at,
            "collection_window": "daily",
            "ccusage_daily_report": ccusage_data,
            "usage_daily": usage_daily,
        }
        if ccusage_session_report is not None:
            payload["ccusage_session_report"] = ccusage_session_report
        if ccusage_blocks_report is not None:
            payload["ccusage_blocks_report"] = ccusage_blocks_report

        # 4. 读取认证 Token 并准备 headers
        headers = {}
        if self.config.token_env:
            token = os.environ.get(self.config.token_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"

        # 5. 上报 HTTP
        try:
            status_code, resp_data = self.http_client.post(
                url=self.config.server_url,
                data=payload,
                headers=headers,
                timeout=float(self.config.timeout_seconds),
            )
        except Exception as exc:
            return {
                "success": False,
                "error_type": "http_request_failed",
                "error_message": f"HTTP request failed: {exc}",
            }

        # 6. 处理响应状态
        if status_code in {401, 403}:
            return {
                "success": False,
                "error_type": "http_auth_failed",
                "error_message": resp_data.get("message") or "Authentication failed at Ingest Server",
            }
        elif status_code != 200:
            return {
                "success": False,
                "error_type": "http_request_failed",
                "error_message": f"Server returned error code {status_code}: {resp_data.get('message') or 'Unknown'}",
            }

        return {
            "success": True,
            "status": resp_data.get("status") or "accepted",
            "source_id": resp_data.get("source_id") or self.config.source_id,
        }

    def _push_source_status(self, status: str, error_type: str, error_message: str) -> Dict[str, Any]:
        observed_at = datetime.now(dt_timezone.utc).astimezone().isoformat()
        payload = {
            "schema_version": self.config.schema_version,
            "source_id": self.config.source_id,
            "host": self.config.host,
            "machine": self.config.machine,
            "os_user": self.config.os_user,
            "platform": self.config.platform,
            "timezone": self.config.timezone,
            "observed_at": observed_at,
            "collection_window": "daily",
            "collection_status": status,
            "error_type": error_type,
            "error_message": error_message,
            "usage_daily": [],
        }
        headers = {}
        if self.config.token_env:
            token = os.environ.get(self.config.token_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        try:
            status_code, resp_data = self.http_client.post(
                url=self.config.server_url,
                data=payload,
                headers=headers,
                timeout=float(self.config.timeout_seconds),
            )
        except Exception as exc:
            return {
                "success": False,
                "error_type": "http_request_failed",
                "error_message": f"HTTP request failed: {exc}",
            }
        if status_code in {401, 403}:
            return {
                "success": False,
                "error_type": "http_auth_failed",
                "error_message": resp_data.get("message") or "Authentication failed at Ingest Server",
            }
        if status_code != 200:
            return {
                "success": False,
                "error_type": "http_request_failed",
                "error_message": f"Server returned error code {status_code}: {resp_data.get('message') or 'Unknown'}",
            }
        return {
            "success": True,
            "status": resp_data.get("status") or "accepted",
            "source_id": resp_data.get("source_id") or self.config.source_id,
            "collection_status": status,
        }
