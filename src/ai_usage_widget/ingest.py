from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .auth import TokenAuthenticator
from .version_contract import (
    COLLECTOR_RELEASE_FIELD,
    VersionContractError,
    normalize_collector_release,
)


class IngestValidationError(ValueError):
    """Ingest payload 校验失败时抛出的异常，支持结构化错误类型"""
    def __init__(self, message: str, error_type: str = "http_schema_invalid"):
        super().__init__(message)
        self.error_type = error_type


@dataclass
class IngestRequest:
    schema_version: int
    source_id: str
    host: str
    os_user: str
    platform: str
    timezone: str
    observed_at: str
    collection_window: str
    usage_daily: List[Dict[str, Any]]
    ccusage_daily_report: Optional[Dict[str, Any]] = None
    ccusage_daily_status: Optional[Dict[str, Any]] = None
    ccusage_session_report: Optional[Dict[str, Any]] = None
    ccusage_blocks_report: Optional[Dict[str, Any]] = None
    mswusage_codex_hourly_report: Optional[Dict[str, Any]] = None
    codex_hourly_status: Optional[Dict[str, Any]] = None
    usage_hourly_facts: Optional[List[Dict[str, Any]]] = None
    usage_ledger_runs: Optional[List[Dict[str, Any]]] = None
    collector_release: Optional[Dict[str, Any]] = None
    machine: Optional[str] = None
    collection_status: str = "ok"
    error_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class IngestResponse:
    status: str
    source_id: str
    accepted_at: str
    message: str
    facts_accepted: int = 0
    version: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "status": self.status,
            "source_id": self.source_id,
            "accepted_at": self.accepted_at,
            "facts_accepted": self.facts_accepted,
            "message": self.message,
        }
        if self.version is not None:
            payload["version"] = self.version
        return payload


def validate_ingest_payload(
    payload: Dict[str, Any],
    token: Optional[str] = None,
    expected_token: Optional[str] = None,
    authenticator: Optional[TokenAuthenticator] = None,
) -> IngestRequest:
    """
    校验终端 push 上报的数据 payload，包含认证验证与大小限制。
    如果不符合契约或认证失败，抛出 IngestValidationError。
    """
    # 1. 认证校验 (TP-V2-002 Ingest Auth)
    active_authenticator = authenticator or TokenAuthenticator.from_values(expected_token)
    if active_authenticator.is_required:
        if not token:
            raise IngestValidationError("Missing authorization token", error_type="http_auth_failed")
        if not active_authenticator.verify(token):
            # 异常信息中不能泄露明文 token
            raise IngestValidationError("Invalid authorization token", error_type="http_auth_failed")

    if not isinstance(payload, dict):
        raise IngestValidationError("Payload must be a JSON object", error_type="http_schema_invalid")

    # 2. 限制 Payload 大小 (2MB 限制)
    try:
        payload_str = json.dumps(payload)
        if len(payload_str.encode("utf-8")) > 50 * 1024 * 1024:
            raise IngestValidationError("Payload size exceeds 50MB limit", error_type="http_schema_invalid")
    except (TypeError, ValueError) as e:
        raise IngestValidationError(f"Payload serialization failed: {e}", error_type="http_schema_invalid")

    # 3. 检验必需字段
    required_fields = ["schema_version", "source_id", "host", "os_user", "timezone", "observed_at"]
    for field in required_fields:
        if field not in payload:
            raise IngestValidationError(f"Missing required field: {field}", error_type="http_schema_invalid")

    # 4. 检验 schema_version
    schema_version = payload["schema_version"]
    if not isinstance(schema_version, int):
        raise IngestValidationError(f"schema_version must be an integer, got: {schema_version}", error_type="http_schema_invalid")

    # 5. 扫描原始日志敏感内容（.claude, .codex）与 SSH 安全漏洞
    def scan_sensitive_values(data: Any) -> None:
        if isinstance(data, str):
            lower_val = data.lower()
            if ".claude" in lower_val or ".codex" in lower_val:
                raise IngestValidationError(f"Sensitive logs path or pattern detected in payload: {data}", error_type="http_schema_invalid")
        elif isinstance(data, dict):
            for k, v in data.items():
                lower_key = str(k).lower()
                if "ssh" in lower_key:
                    raise IngestValidationError(f"SSH parameters are forbidden in payload key: {k}", error_type="http_schema_invalid")
                if ".claude" in lower_key or ".codex" in lower_key:
                    raise IngestValidationError(f"Sensitive logs key detected in payload: {k}", error_type="http_schema_invalid")
                scan_sensitive_values(v)
        elif isinstance(data, list):
            for item in data:
                scan_sensitive_values(item)

    scan_sensitive_values(payload)

    ccusage_daily_report = payload.get("ccusage_daily_report")
    if ccusage_daily_report is not None and not isinstance(ccusage_daily_report, dict):
        raise IngestValidationError("ccusage_daily_report must be an object", error_type="http_schema_invalid")
    ccusage_daily_status = payload.get("ccusage_daily_status")
    if ccusage_daily_status is not None and not isinstance(ccusage_daily_status, dict):
        raise IngestValidationError("ccusage_daily_status must be an object", error_type="http_schema_invalid")
    if isinstance(ccusage_daily_status, dict):
        for key in ["status", "error_type", "error_message"]:
            if key not in ccusage_daily_status:
                raise IngestValidationError(
                    f"ccusage_daily_status.{key} is required",
                    error_type="http_schema_invalid",
                )
    ccusage_session_report = payload.get("ccusage_session_report")
    if ccusage_session_report is not None and not isinstance(ccusage_session_report, dict):
        raise IngestValidationError("ccusage_session_report must be an object", error_type="http_schema_invalid")
    ccusage_blocks_report = payload.get("ccusage_blocks_report")
    if ccusage_blocks_report is not None and not isinstance(ccusage_blocks_report, dict):
        raise IngestValidationError("ccusage_blocks_report must be an object", error_type="http_schema_invalid")
    mswusage_codex_hourly_report = payload.get("mswusage_codex_hourly_report")
    if mswusage_codex_hourly_report is not None and not isinstance(mswusage_codex_hourly_report, dict):
        raise IngestValidationError("mswusage_codex_hourly_report must be an object", error_type="http_schema_invalid")
    codex_hourly_status = payload.get("codex_hourly_status")
    if codex_hourly_status is not None and not isinstance(codex_hourly_status, dict):
        raise IngestValidationError("codex_hourly_status must be an object", error_type="http_schema_invalid")
    usage_hourly_facts = payload.get("usage_hourly_facts")
    if usage_hourly_facts is not None:
        if not isinstance(usage_hourly_facts, list):
            raise IngestValidationError("usage_hourly_facts must be a list", error_type="http_schema_invalid")
        for index, fact in enumerate(usage_hourly_facts):
            if not isinstance(fact, dict):
                raise IngestValidationError(
                    f"usage_hourly_facts[{index}] must be an object",
                    error_type="http_schema_invalid",
                )
            for key in ["fact_id", "agent", "window_start", "window_end", "usage", "attribution_confidence", "provenance"]:
                if key not in fact:
                    raise IngestValidationError(
                        f"usage_hourly_facts[{index}].{key} is required",
                        error_type="http_schema_invalid",
                    )
            if not isinstance(fact.get("usage"), dict):
                raise IngestValidationError(
                    f"usage_hourly_facts[{index}].usage must be an object",
                    error_type="http_schema_invalid",
                )
            if not isinstance(fact.get("ai_account", {}), dict):
                raise IngestValidationError(
                    f"usage_hourly_facts[{index}].ai_account must be an object",
                    error_type="http_schema_invalid",
                )
    usage_ledger_runs = payload.get("usage_ledger_runs")
    if usage_ledger_runs is not None:
        if not isinstance(usage_ledger_runs, list):
            raise IngestValidationError("usage_ledger_runs must be a list", error_type="http_schema_invalid")
        for index, run in enumerate(usage_ledger_runs):
            if not isinstance(run, dict) or not run.get("agent") or not run.get("provenance") or not isinstance(run.get("collector"), dict) or not isinstance(run.get("facts_digest"), str):
                raise IngestValidationError(
                    f"usage_ledger_runs[{index}] is incomplete",
                    error_type="http_schema_invalid",
                )

    # 6. 采集端版本块：缺整块只降级为 None，不抛错；出现不合法值才明确拒绝。
    #    错误信息只带字段名，不回显值，避免疑似凭据进入日志或错误响应。
    try:
        collector_release = normalize_collector_release(payload.get(COLLECTOR_RELEASE_FIELD))
    except VersionContractError as exc:
        raise IngestValidationError(str(exc), error_type="http_schema_invalid") from exc

    # 7. 构建并返回 IngestRequest
    return IngestRequest(
        schema_version=schema_version,
        source_id=str(payload["source_id"]),
        host=str(payload["host"]),
        machine=str(payload["machine"]) if payload.get("machine") else None,
        os_user=str(payload["os_user"]),
        platform=str(payload.get("platform", "unknown")),
        timezone=str(payload["timezone"]),
        observed_at=str(payload["observed_at"]),
        collection_window=str(payload.get("collection_window", "daily")),
        usage_daily=list(payload.get("usage_daily", [])),
        ccusage_daily_report=ccusage_daily_report,
        ccusage_daily_status=ccusage_daily_status,
        ccusage_session_report=ccusage_session_report,
        ccusage_blocks_report=ccusage_blocks_report,
        mswusage_codex_hourly_report=mswusage_codex_hourly_report,
        codex_hourly_status=codex_hourly_status,
        usage_hourly_facts=usage_hourly_facts,
        usage_ledger_runs=usage_ledger_runs,
        collector_release=collector_release,
        collection_status=str(payload.get("collection_status") or "ok"),
        error_type=str(payload["error_type"]) if payload.get("error_type") else None,
        error_message=str(payload["error_message"]) if payload.get("error_message") else None,
    )
