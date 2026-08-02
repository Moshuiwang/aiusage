from __future__ import annotations

import json
import hashlib
import os
import shlex
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone as dt_timezone
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .collector_store import (
    DELIVERED,
    KIND_USAGE,
    TERMINAL,
    CollectorStore,
    OutboxConfig,
    OutboxFull,
    OutboxNotDrained,
    classify_delivery,
)
from .config import DeviceConfig
from .http_identity import PRODUCT_USER_AGENT
from .models import CommandResult
from .version_contract import (
    COLLECTOR_RELEASE_FIELD,
    UNSUPPORTED_ERROR_TYPE,
    VersionContractError,
    local_collector_release,
)


class IngestHTTPClient:
    """Ingest API 的 HTTP 客户端基类，默认使用 Python 标准库 urllib.request 实现"""
    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        req_data = json.dumps(data).encode("utf-8")
        req_headers = headers.copy()
        req_headers["Content-Type"] = "application/json"
        req_headers.setdefault("User-Agent", PRODUCT_USER_AGENT)

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


def _is_mswusage_codex_report(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("source") == "mswusage_codex"
        and value.get("provenance") == "mswusage_codex_token_count"
        and isinstance(value.get("hourly"), list)
        and isinstance(value.get("daily"), list)
        and isinstance(value.get("sessions"), list)
    )


def _is_mswusage_claude_report(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("source") == "mswusage_claude"
        and value.get("provenance") == "mswusage_claude_assistant_usage"
        and isinstance(value.get("hourly"), list)
        and isinstance(value.get("daily"), list)
        and isinstance(value.get("sessions"), list)
    )


def _codex_hourly_drift(ccusage_data: dict, mswusage_report: dict, threshold_percent: float = 5.0) -> dict:
    daily_by_date, baseline_agent = _ccusage_codex_totals_by_date(ccusage_data)
    mswusage_dates = _mswusage_codex_dates(mswusage_report)
    latest_date = max(set(daily_by_date) & mswusage_dates) if set(daily_by_date) & mswusage_dates else None
    comparison_dates = [latest_date] if latest_date else []
    daily_total = sum(daily_by_date[date] for date in comparison_dates) if comparison_dates else None
    mswusage_total = _mswusage_codex_total(mswusage_report, comparison_dates) if comparison_dates else None
    result = {
        "status": "comparison_unavailable",
        "threshold_percent": threshold_percent,
        "daily_codex_total_tokens": daily_total,
        "mswusage_codex_total_tokens": mswusage_total,
        "comparison_dates": comparison_dates,
        "baseline_agent": baseline_agent,
    }
    if daily_total is None or mswusage_total is None:
        return result
    if daily_total == 0:
        difference_percent = 0.0 if mswusage_total == 0 else 100.0
        difference_tokens = abs(mswusage_total)
    else:
        difference_tokens = abs(mswusage_total - daily_total)
        difference_percent = round((difference_tokens / daily_total) * 100, 4)
    result["difference_tokens"] = difference_tokens
    result["difference_percent"] = difference_percent
    result["status"] = "ok" if difference_percent <= threshold_percent else "drift_detected"
    return result


def _ccusage_codex_totals_by_date(ccusage_data: dict) -> tuple[dict[str, int], str | None]:
    rows = ccusage_data.get("daily") if isinstance(ccusage_data, dict) else None
    if not isinstance(rows, list):
        return {}, None
    totals: dict[str, int] = {}
    all_totals: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = row.get("period")
        if not date:
            continue
        agent = str(row.get("agent") or "").lower()
        if _is_codex_agent(agent):
            totals[str(date)] = totals.get(str(date), 0) + int(row.get("totalTokens") or 0)
        elif agent == "all":
            all_totals[str(date)] = all_totals.get(str(date), 0) + int(row.get("totalTokens") or 0)
    if totals:
        return totals, "codex"
    if all_totals:
        return all_totals, "all"
    return {}, None


def _mswusage_codex_total(report: dict, dates: list[str]) -> int | None:
    rows = report.get("daily") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return None
    date_set = set(dates)
    total = 0
    found = False
    for row in rows:
        if not isinstance(row, dict) or not _is_codex_agent(row.get("agent")):
            continue
        if str(row.get("date")) not in date_set:
            continue
        found = True
        total += int(row.get("total_tokens") or 0)
    return total if found else None


def _mswusage_codex_dates(report: dict) -> set[str]:
    rows = report.get("daily") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return set()
    dates = set()
    for row in rows:
        if isinstance(row, dict) and _is_codex_agent(row.get("agent")) and row.get("date"):
            dates.add(str(row["date"]))
    return dates


def _is_codex_agent(agent: Any) -> bool:
    raw = str(agent or "").lower()
    return "codex" in raw or "gpt" in raw or "openai" in raw


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
        retry_attempts: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
        ledger_mode: str = "incremental",
        ledger_lookback_hours: float = 48.0,
        ledger_coverage_start: str | None = None,
        outbox: CollectorStore | None = None,
    ) -> None:
        self.config = config
        self.executor = executor
        # 注入的 store 由调用方负责关闭；pusher 自己按配置打开的那个用完即关。
        self._outbox = outbox
        self.http_client = http_client
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_sleep = retry_sleep
        if ledger_mode not in {"incremental", "full-rescan"}:
            raise ValueError("ledger_mode must be incremental or full-rescan")
        self.ledger_mode = ledger_mode
        self.ledger_lookback_hours = max(float(ledger_lookback_hours), 1.0)
        self.ledger_coverage_start = ledger_coverage_start

    def push(self) -> Dict[str, Any]:
        """
        执行本地采集并主动将 daily usage payload 推送至 HTTP Ingest Server
        """
        # 1. 采集 ccusage 报告
        # ccusage daily --json --timezone <config.timezone>
        argv = ["ccusage", "daily", "--json", "--timezone", self.config.timezone]
        res = self.executor(argv, float(self.config.timeout_seconds))

        ccusage_data: dict[str, Any] = {}
        usage_daily: list[dict[str, Any]] = []
        ccusage_daily_status = None
        ccusage_daily_available = False

        # 2. 解析 ccusage 的数据并规范化 (TP-V2-006)
        if res.ok:
            try:
                parsed_ccusage = json.loads(res.stdout) if res.stdout else {}
                if not isinstance(parsed_ccusage, dict):
                    ccusage_daily_status = {
                        "status": "unsupported_shape",
                        "error_type": "unsupported_shape",
                        "error_message": "ccusage JSON must be an object",
                    }
                else:
                    ccusage_data = parsed_ccusage
                    ccusage_daily_available = True
                    raw_daily = ccusage_data.get("daily", [])
                    if not isinstance(raw_daily, list):
                        raw_daily = []
                    for row in raw_daily:
                        if isinstance(row, dict):
                            normalized_row = row.copy()
                            if not normalized_row.get("agent"):
                                normalized_row["agent"] = "unknown"
                            usage_daily.append(normalized_row)
            except json.JSONDecodeError as exc:
                ccusage_daily_status = {
                    "status": "invalid_json",
                    "error_type": "invalid_json",
                    "error_message": f"Failed to decode ccusage JSON: {exc}",
                }
        else:
            ccusage_daily_status = {
                "status": res.error_type or "command_failed",
                "error_type": res.error_type or "command_failed",
                "error_message": res.error_message or "ccusage command failed",
            }

        ccusage_session_report = None
        if ccusage_daily_available:
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
        if ccusage_daily_available:
            blocks_argv = ["ccusage", "blocks", "--json", "--timezone", self.config.timezone]
            blocks_res = self.executor(blocks_argv, float(self.config.timeout_seconds))
            if blocks_res.ok and blocks_res.stdout:
                try:
                    blocks_data = json.loads(blocks_res.stdout)
                    if isinstance(blocks_data, dict) and isinstance(blocks_data.get("blocks"), list):
                        ccusage_blocks_report = blocks_data
                except json.JSONDecodeError:
                    ccusage_blocks_report = None

        mswusage_codex_hourly_report = None
        codex_hourly_status = None
        mswusage_argv = [
            sys.executable,
            "-m",
            "ai_usage_widget.cli",
            "mswusage-codex",
            "--json",
            "--timezone",
            self.config.timezone,
            "--mode",
            self.ledger_mode,
        ]
        if self.ledger_mode == "incremental":
            mswusage_argv.extend(["--lookback-hours", f"{self.ledger_lookback_hours:g}"])
        elif self.ledger_coverage_start:
            mswusage_argv.extend(["--coverage-start", self.ledger_coverage_start])
        mswusage_res = self.executor(mswusage_argv, float(self.config.timeout_seconds))
        if mswusage_res.ok and mswusage_res.stdout:
            try:
                report = json.loads(mswusage_res.stdout)
                if _is_mswusage_codex_report(report):
                    report["drift"] = _codex_hourly_drift(ccusage_data, report)
                    mswusage_codex_hourly_report = report
            except json.JSONDecodeError:
                codex_hourly_status = {
                    "source": "mswusage_codex",
                    "status": "unavailable",
                    "error_type": "invalid_json",
                }
        elif not mswusage_res.ok:
            codex_hourly_status = {
                "source": "mswusage_codex",
                "status": "unavailable",
                "error_type": mswusage_res.error_type or "command_failed",
            }

        mswusage_claude_report = None
        claude_argv = [
            sys.executable,
            "-m",
            "ai_usage_widget.cli",
            "mswusage-claude",
            "--json",
            "--timezone",
            self.config.timezone,
            "--mode",
            self.ledger_mode,
        ]
        if self.ledger_mode == "incremental":
            claude_argv.extend(["--lookback-hours", f"{self.ledger_lookback_hours:g}"])
        elif self.ledger_coverage_start:
            claude_argv.extend(["--coverage-start", self.ledger_coverage_start])
        claude_res = self.executor(claude_argv, float(self.config.timeout_seconds))
        if claude_res.ok and claude_res.stdout:
            try:
                report = json.loads(claude_res.stdout)
                if _is_mswusage_claude_report(report):
                    mswusage_claude_report = report
            except json.JSONDecodeError:
                mswusage_claude_report = None

        ledger_collection_available = (
            mswusage_codex_hourly_report is not None
            or mswusage_claude_report is not None
        )
        if ccusage_daily_status is not None and not ledger_collection_available:
            return self._push_source_status(
                status=str(ccusage_daily_status["status"]),
                error_type=str(ccusage_daily_status["error_type"]),
                error_message=str(ccusage_daily_status["error_message"]),
            )

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
            "collection_status": "ok",
            "usage_daily": usage_daily,
            COLLECTOR_RELEASE_FIELD: _local_collector_release(self.config),
        }
        if ccusage_daily_available:
            payload["ccusage_daily_report"] = ccusage_data
        if ccusage_daily_status is not None:
            payload["ccusage_daily_status"] = ccusage_daily_status
        if ccusage_session_report is not None:
            payload["ccusage_session_report"] = ccusage_session_report
        if ccusage_blocks_report is not None:
            payload["ccusage_blocks_report"] = ccusage_blocks_report
        if mswusage_codex_hourly_report is not None:
            payload["mswusage_codex_hourly_report"] = mswusage_codex_hourly_report
            hourly_facts = _usage_hourly_facts_from_mswusage(
                self.config,
                mswusage_codex_hourly_report,
                provider_key="codex",
                default_provider="openai",
                default_agent="codex",
                default_client="codex",
            )
            if hourly_facts:
                payload["usage_hourly_facts"] = hourly_facts
            ledger_run = _usage_ledger_run(mswusage_codex_hourly_report, hourly_facts, agent="codex")
            if ledger_run is not None:
                payload.setdefault("usage_ledger_runs", []).append(ledger_run)
        elif codex_hourly_status is not None:
            payload["codex_hourly_status"] = codex_hourly_status
        if mswusage_claude_report is not None:
            hourly_facts = _usage_hourly_facts_from_mswusage(
                self.config,
                mswusage_claude_report,
                provider_key="claude",
                default_provider="claude",
                default_agent="claude",
                default_client="claude",
            )
            if hourly_facts:
                payload.setdefault("usage_hourly_facts", []).extend(hourly_facts)
            ledger_run = _usage_ledger_run(mswusage_claude_report, hourly_facts, agent="claude")
            if ledger_run is not None:
                payload.setdefault("usage_ledger_runs", []).append(ledger_run)

        # 4. 读取认证 Token 并准备 headers
        headers = {"User-Agent": PRODUCT_USER_AGENT}
        if self.config.token_env:
            token = os.environ.get(self.config.token_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"

        # 5. 投递（直推 或 经本地 outbox 持久缓冲后补推）
        return self._deliver(payload, headers)

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
            COLLECTOR_RELEASE_FIELD: _local_collector_release(self.config),
        }
        headers = {"User-Agent": PRODUCT_USER_AGENT}
        if self.config.token_env:
            token = os.environ.get(self.config.token_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        # 状态心跳是「当前状态」，不是不可再生的历史：`usage_daily` 是空的，下一轮采集
        # 会重新产生同样的结论。「采集坏了 + 网也断了」会同时发生，如果每轮心跳都被
        # 无限缓冲，磁盘上限会被这些可再生的心跳吃光，之后真正不可再生的用量 payload
        # 反而被 outbox_full 拒之门外——防丢数的机制亲手造成丢数。所以按 dedupe_key
        # 只保留最新一条，并给它 TTL。
        return self._deliver(
            payload,
            headers,
            success_extra={"collection_status": status},
            dedupe_key="source_status",
            ttl_seconds=self._status_heartbeat_ttl(),
        )

    def _status_heartbeat_ttl(self) -> float | None:
        outbox_config = getattr(self.config, "outbox", None)
        return outbox_config.limit_ttl_seconds if outbox_config is not None else None

    # --- 投递 ---------------------------------------------------------------
    #
    # 采集与投递是两件事：采集只发生在本机、结果是这份 payload；投递可能失败、可能要
    # 跨天补推。#73 把「投递」从 push() 里单独拆出来，正常路径与失败路径共用同一条，
    # 免得两处各写一份重试语义再慢慢漂移。

    def _deliver(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        *,
        success_extra: Dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        ttl_seconds: float | None = None,
    ) -> Dict[str, Any]:
        outbox_config = getattr(self.config, "outbox", None)

        if outbox_config is None and self._outbox is None:
            # 这台设备从来没启用过 outbox：走原来的直推路径，行为一个字节都不变。
            return self._deliver_direct(payload, headers, success_extra)

        # outbox 是本次新引入的故障源（库被锁、磁盘只读、文件损坏）。它自己坏掉时
        # 必须返回结构化失败，而不是把整次采集变成一个栈回溯——`cli.py` 的 except
        # 子句接不住 `sqlite3.Error`。**也绝不退化成静默直推**：那会让数据看似送出去了，
        # 磁盘上的积压却再没人管，比直接报错更难发现。
        try:
            return self._deliver_with_outbox(
                payload, headers, outbox_config, success_extra, dedupe_key, ttl_seconds
            )
        except sqlite3.Error as exc:
            return {
                "success": False,
                "error_type": "outbox_unavailable",
                "error_message": f"本地 outbox 不可用，本次上报未送达：{exc}",
            }

    def _deliver_with_outbox(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        outbox_config: OutboxConfig | None,
        success_extra: Dict[str, Any] | None,
        dedupe_key: str | None,
        ttl_seconds: float | None,
    ) -> Dict[str, Any]:
        if self._outbox is not None and (outbox_config is None or outbox_config.enabled):
            return self._deliver_via_outbox(
                self._outbox, payload, headers, outbox_config, success_extra, dedupe_key, ttl_seconds
            )

        if outbox_config is not None and not outbox_config.enabled:
            # 已回退到直推。回退**不允许静默丢弃**：磁盘上还有未交付数据就当场停下，
            # 而不是绕过它继续直推——那些数据没人会再看一眼。
            blocked = self._drain_guard(outbox_config)
            if blocked is not None:
                return blocked
            return self._deliver_direct(payload, headers, success_extra)

        assert outbox_config is not None
        store = CollectorStore.from_config(outbox_config)
        try:
            return self._deliver_via_outbox(
                store, payload, headers, outbox_config, success_extra, dedupe_key, ttl_seconds
            )
        finally:
            store.close()

    def _deliver_direct(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        success_extra: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        try:
            status_code, resp_data = self._post_with_retries(
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
        result = self._interpret_response(status_code, resp_data)
        if result.get("success") and success_extra:
            result.update(success_extra)
        return result

    def _deliver_via_outbox(
        self,
        store: CollectorStore,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        outbox_config: OutboxConfig | None,
        success_extra: Dict[str, Any] | None,
        dedupe_key: str | None = None,
        ttl_seconds: float | None = None,
    ) -> Dict[str, Any]:
        """先落盘，再尽力补推。**先落盘**是这个顺序的全部意义所在。

        payload 一旦进了 outbox，进程被杀、机器断电、网络断三天都不会让它消失；
        补推失败只是「这次没送到」，不是「这段历史没了」。
        """
        store.purge_expired()
        batch = outbox_config.max_flush_batch if outbox_config is not None else None
        try:
            entry_id = store.enqueue(
                payload, kind=KIND_USAGE, dedupe_key=dedupe_key, ttl_seconds=ttl_seconds
            )
        except OutboxFull as exc:
            # 磁盘上限：拒绝新增而不是丢最旧（理由见 collector_store 模块 docstring）。
            # 但「满了」不等于「卡死」：先把积压尽力推掉腾出空间，再试一次入队。
            # 少了这一步，磁盘一旦打满就再也回不来了——网络恢复也没用，
            # 因为补推根本不会被触发。
            self._flush_outbox(store, headers, limit=batch)
            try:
                entry_id = store.enqueue(
                    payload, kind=KIND_USAGE, dedupe_key=dedupe_key, ttl_seconds=ttl_seconds
                )
            except OutboxFull:
                # 仍然放不下：**显式失败**，让运维立刻看见，
                # 而不是悄悄牺牲一段已经缓冲下来的历史。
                return {
                    "success": False,
                    "error_type": "outbox_full",
                    "error_message": str(exc),
                    "outbox": store.stats(),
                }

        outcomes = self._flush_outbox(store, headers, limit=batch)

        result = dict(
            outcomes.get(entry_id)
            or {
                "success": False,
                "error_type": "outbox_queued",
                "error_message": (
                    "本次 payload 已持久化到本地 outbox，等待网络恢复后补推；"
                    "本次上报未送达服务端"
                ),
            }
        )
        if result.get("success") and success_extra:
            result.update(success_extra)
        result["outbox"] = store.stats()
        return result

    def _flush_outbox(
        self,
        store: CollectorStore,
        headers: Dict[str, str],
        *,
        limit: int | None,
    ) -> Dict[int, Dict[str, Any]]:
        """按入队顺序补推，返回每个条目各自的投递结果。

        遇到可重试失败就**停下**：网络不通时继续硬打后面几十条只会拖长采集耗时，
        而它们下一轮还在。终态失败则跳过该条继续——一条永远收不下的 payload
        不该把它后面的历史一起堵死。
        """
        outcomes: Dict[int, Dict[str, Any]] = {}
        for entry in store.pending(limit=limit):
            try:
                status_code, resp_data = self._post_with_retries(
                    url=self.config.server_url,
                    data=entry.payload,
                    headers=headers,
                    timeout=float(self.config.timeout_seconds),
                )
            except Exception as exc:
                outcomes[entry.entry_id] = {
                    "success": False,
                    "error_type": "http_request_failed",
                    "error_message": f"HTTP request failed: {exc}",
                }
                store.record_failure(entry.entry_id, f"http_request_failed: {exc}")
                break

            interpreted = self._interpret_response(status_code, resp_data)
            outcomes[entry.entry_id] = interpreted
            verdict = classify_delivery(status_code, resp_data)
            reason = f"{interpreted.get('error_type')}: {interpreted.get('error_message')}"
            if verdict == DELIVERED:
                store.ack(entry.entry_id)
            elif verdict == TERMINAL:
                store.dead_letter(entry.entry_id, reason=reason)
            else:
                store.record_failure(entry.entry_id, reason)
                break
        return outcomes

    def _drain_guard(self, outbox_config: OutboxConfig) -> Dict[str, Any] | None:
        """回退到直推前的排空检查。返回 ``None`` 表示放行。"""
        store = self._outbox
        owned = False
        if store is None:
            if not Path(outbox_config.path).exists():
                return None
            store = CollectorStore.from_config(outbox_config)
            owned = True
        try:
            store.assert_drained()
        except OutboxNotDrained as exc:
            return {
                "success": False,
                "error_type": "outbox_not_drained",
                "error_message": str(exc),
            }
        finally:
            if owned:
                store.close()
        return None

    def _interpret_response(self, status_code: int, resp_data: dict) -> Dict[str, Any]:
        """把一次 HTTP 响应翻译成 push 结果。正常路径与失败路径共用同一份判定。"""
        if status_code == 401:
            return {
                "success": False,
                "error_type": "http_auth_failed",
                "error_message": resp_data.get("message") or "Authentication failed at Ingest Server",
            }
        if status_code == 403:
            return {
                "success": False,
                "error_type": "http_access_blocked",
                "error_message": resp_data.get("message") or "入口防护拦截或访问被拒绝，请检查网络入口策略",
            }
        if resp_data.get("error_type") == UNSUPPORTED_ERROR_TYPE:
            return {
                "success": False,
                "error_type": UNSUPPORTED_ERROR_TYPE,
                "error_message": resp_data.get("message") or "采集端版本不被服务端支持，本次上报未写入",
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
        }

    def _post_with_retries(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                return self.http_client.post(url=url, data=data, headers=headers, timeout=timeout)
            except Exception as exc:
                last_exc = exc
                if attempt < self.retry_attempts - 1:
                    self.retry_sleep(0.5)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("HTTP request failed without an exception")


def _usage_hourly_facts_from_mswusage(
    config: DeviceConfig,
    report: dict,
    *,
    provider_key: str = "codex",
    default_provider: str = "openai",
    default_agent: str = "codex",
    default_client: str = "codex",
) -> list[dict[str, Any]]:
    accounts = config.ai_accounts or {}
    account = accounts.get(provider_key)
    account_confirmed = isinstance(account, dict)
    if not account_confirmed:
        account = {}
    rows = report.get("hourly")
    if not isinstance(rows, list):
        return []
    provider = str(account.get("provider") or default_provider)
    account_id = str(
        account.get("account_id")
        or account.get("label")
        or f"unconfirmed_local_source:{config.source_id}:{default_agent}"
    )
    label = str(account.get("label") or "本机来源 / 未确认账号")
    confidence = str(
        account.get("attribution_confidence")
        or ("account_observed_usage_inferred" if account_confirmed else "unconfirmed_local_source")
    )
    provenance_default = str(report.get("provenance") or f"mswusage_{default_agent}_usage")
    collector = report.get("collector") if isinstance(report.get("collector"), dict) else {}
    coverage = collector.get("coverage") if isinstance(collector.get("coverage"), dict) else {}
    coverage_start = str(coverage.get("start")) if coverage.get("start") else None
    coverage_end = str(coverage.get("end")) if coverage.get("end") else None
    facts = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("hour"):
            continue
        hour = str(row["hour"])
        if coverage_start and hour < coverage_start:
            continue
        if coverage_end and hour >= coverage_end:
            continue
        window_start = hour
        window_end = str(row.get("window_end") or _next_hour_iso(hour) or hour)
        provenance = str(row.get("provenance") or provenance_default)
        fact = {
            "fact_id": f"{provider_key}:{default_client}:{config.source_id}:{window_start}:{window_end}:{confidence}:{provider}:{account_id}:{provenance}",
            "agent": default_agent,
            "client": default_client,
            "window_start": window_start,
            "window_end": window_end,
            "ai_account": {
                "provider": provider,
                "account_id": account_id,
                "label": label,
                "display_name": account.get("display_name"),
                "subscription": account.get("subscription"),
            },
            "usage": {
                "input_tokens": int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "cache_creation_tokens": int(row.get("cache_creation_tokens") or 0),
                "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
                "reasoning_output_tokens": int(row.get("reasoning_output_tokens") or 0),
                "total_tokens": int(row.get("total_tokens") or 0),
            },
            "event_count": int(row.get("event_count") or 0),
            "session_count": int(row.get("session_count") or 0),
            "attribution_confidence": confidence,
            "provenance": provenance,
            "account_evidence": {
                "source": str(account.get("evidence_source") or ("device_config" if account_confirmed else "local_usage_ledger")),
                "observed_at": report.get("generated_at"),
                "window": "collection_time",
            },
            "sensitive_payload": False,
        }
        if isinstance(report.get("collector"), dict):
            fact["metadata"] = {"collector": report["collector"]}
        facts.append(fact)
    return facts


def _local_collector_release(config: DeviceConfig) -> dict[str, Any]:
    """构造本机要上报的采集端版本块。

    build_sha 和最后升级结果来自环境变量，未来由自升级 agent 写入。
    任何一层给了不合规的值就**逐层丢掉该来源**并退回更安全的默认值：
    既不让疑似凭据出网，也不因为一个环境变量或一项配置写错就中断整次采集上报。
    最后一层只含代码常量，永远合法。
    """
    candidates: list[dict[str, Any]] = [
        {
            "config_schema_version": config.schema_version,
            "release_channel": config.release_channel,
            "build_sha": os.environ.get("AI_USAGE_BUILD_SHA"),
            "last_upgrade": _last_upgrade_from_env(),
        },
        {
            "config_schema_version": config.schema_version,
            "release_channel": config.release_channel,
        },
        {},
    ]
    for kwargs in candidates:
        try:
            return local_collector_release(**kwargs)
        except VersionContractError:
            continue
    raise AssertionError("local_collector_release() 的常量兜底不应失败")


def _last_upgrade_from_env() -> dict[str, Any] | None:
    status = os.environ.get("AI_USAGE_LAST_UPGRADE_STATUS")
    if not status:
        return None
    last_upgrade: dict[str, Any] = {"status": status}
    for key, env_name in (
        ("from_version", "AI_USAGE_LAST_UPGRADE_FROM_VERSION"),
        ("to_version", "AI_USAGE_LAST_UPGRADE_TO_VERSION"),
        ("finished_at", "AI_USAGE_LAST_UPGRADE_FINISHED_AT"),
    ):
        value = os.environ.get(env_name)
        if value:
            last_upgrade[key] = value
    return last_upgrade


def _usage_ledger_run(report: dict, facts: list[dict[str, Any]], *, agent: str) -> dict[str, Any] | None:
    collector = report.get("collector")
    if not isinstance(collector, dict):
        return None
    return {
        "agent": agent,
        "provenance": str(report.get("provenance") or f"mswusage_{agent}_usage"),
        "collector": collector,
        "facts_digest": _facts_digest(facts, collector),
    }


def _facts_digest(facts: list[dict[str, Any]], collector: dict) -> str:
    coverage = collector.get("coverage") if isinstance(collector.get("coverage"), dict) else {}
    start = coverage.get("start")
    end = coverage.get("end")
    canonical = []
    for fact in facts:
        window_start = str(fact.get("window_start") or "")
        if start and window_start < str(start):
            continue
        if end and window_start >= str(end):
            continue
        canonical.append({
            key: fact.get(key)
            for key in (
                "fact_id", "agent", "client", "window_start", "window_end", "usage",
                "event_count", "session_count", "attribution_confidence", "provenance",
            )
        })
    encoded = json.dumps(
        sorted(canonical, key=lambda row: str(row["fact_id"])),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _next_hour_iso(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat(timespec="seconds")
