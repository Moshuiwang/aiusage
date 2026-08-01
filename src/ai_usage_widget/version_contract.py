"""版本合同：采集端 / 服务端版本字段口径、四态判定与最低支持版本策略。

本模块是「版本字段口径与兼容状态判定」的唯一 owner（见
`docs/architecture/version-and-upgrade-contract.md`）。它是叶子模块，
不依赖包内其它模块，因此 ingest、service 编排层和 read model 都可以直接引用，
不会形成反向依赖。

安全边界：所有版本字段都用**收紧的字面量白名单**校验（semver / 十六进制 SHA /
枚举 / ISO 时间戳）。token、绝对路径、命令行参数等形态无法通过校验，
因此不可能出现在任何版本字段或来源健康输出里。校验失败的异常信息
**只报字段名，不回显值**，避免把疑似凭据写进日志。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

# --- 四态与降级态 ------------------------------------------------------------

VERSION_STATE_CURRENT = "current"
VERSION_STATE_UPDATE_AVAILABLE = "update_available"
VERSION_STATE_UNSUPPORTED = "unsupported"
VERSION_STATE_ROLLBACK_AVAILABLE = "rollback_available"
VERSION_STATE_UNKNOWN = "unknown"

#: Issue #58 明确要求的四态。`unknown` 不属于四态，是「采集端没报版本」的降级态。
VERSION_STATES = (
    VERSION_STATE_CURRENT,
    VERSION_STATE_UPDATE_AVAILABLE,
    VERSION_STATE_UNSUPPORTED,
    VERSION_STATE_ROLLBACK_AVAILABLE,
)

ALL_VERSION_STATES = VERSION_STATES + (VERSION_STATE_UNKNOWN,)

#: 排序权重，数字越小越需要人工处理。用于来源健康列表的确定性排序。
VERSION_STATE_SEVERITY = {
    VERSION_STATE_UNSUPPORTED: 0,
    VERSION_STATE_ROLLBACK_AVAILABLE: 1,
    VERSION_STATE_UPDATE_AVAILABLE: 2,
    VERSION_STATE_UNKNOWN: 3,
    VERSION_STATE_CURRENT: 4,
}

# --- 采集端本机版本常量 ------------------------------------------------------

COLLECTOR_VERSION = "0.3.0"
COLLECTOR_PARSER_SCHEMA_VERSION = 2
DEFAULT_RELEASE_CHANNEL = "stable"
RELEASE_CHANNELS = ("stable", "beta", "dev")
LAST_UPGRADE_STATUSES = ("never", "succeeded", "failed", "rolled_back")

# --- 服务端版本与兼容策略 ----------------------------------------------------

SERVER_API_VERSION = "1.0.0"
SERVER_READ_MODEL_VERSION = "1.0.0"
SERVER_INGEST_SCHEMA_VERSION = 1
MIN_SUPPORTED_COLLECTOR_VERSION = "0.1.0"
TARGET_COLLECTOR_VERSION = COLLECTOR_VERSION
MIN_SUPPORTED_CONFIG_SCHEMA_VERSION = 1
MIN_SUPPORTED_PARSER_SCHEMA_VERSION = 1

#: ingest payload 里承载采集端版本的顶层 key（wire 格式，嵌套 last_upgrade）。
COLLECTOR_RELEASE_FIELD = "collector_release"

#: wire 格式允许的 key，多一个都拒绝，避免任意数据借版本块夹带上来。
COLLECTOR_RELEASE_WIRE_FIELDS = (
    "collector_version",
    "config_schema_version",
    "parser_schema_version",
    "release_channel",
    "build_sha",
    "last_upgrade",
)

COLLECTOR_RELEASE_LAST_UPGRADE_FIELDS = (
    "status",
    "from_version",
    "to_version",
    "finished_at",
)

#: 内部规范化后的扁平字段名，也是 read model / 存储层使用的字段名。
COLLECTOR_VERSION_FIELDS = (
    "collector_version",
    "config_schema_version",
    "parser_schema_version",
    "release_channel",
    "build_sha",
    "last_upgrade_status",
    "last_upgrade_from_version",
    "last_upgrade_to_version",
    "last_upgrade_finished_at",
)

SERVER_VERSION_FIELDS = (
    "api_version",
    "read_model_version",
    "ingest_schema_version",
    "min_supported_collector_version",
    "target_collector_version",
)

#: 呈现端版本字段（Mac / iPhone / Watch / Web），本轮只定合同，不实现客户端。
PRESENTATION_VERSION_FIELDS = (
    "app_version",
    "build_number",
    "data_contract_version",
)

#: 服务端判定「明确不兼容」后返回的错误类型。不是静默 200，也不是静默丢弃。
UNSUPPORTED_ERROR_TYPE = "collector_version_unsupported"

# --- 校验用字面量白名单 ------------------------------------------------------

_SEMVER_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][0-9A-Za-z][0-9A-Za-z.]{0,31})?$")
_BUILD_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_SCHEMA_VERSION = 10000


class VersionContractError(ValueError):
    """版本字段不符合合同。异常信息只包含字段名，不回显字段值。"""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class VersionPolicy:
    """服务端的兼容策略。`min_*` 是拒绝线，`target_*` 是提示线。"""

    min_supported_collector_version: str = MIN_SUPPORTED_COLLECTOR_VERSION
    target_collector_version: str = TARGET_COLLECTOR_VERSION
    min_supported_config_schema_version: int = MIN_SUPPORTED_CONFIG_SCHEMA_VERSION
    min_supported_parser_schema_version: int = MIN_SUPPORTED_PARSER_SCHEMA_VERSION


DEFAULT_VERSION_POLICY = VersionPolicy()


def compare_versions(left: str, right: str) -> int:
    """按 semver 语义比较两个版本号，返回 -1 / 0 / 1。"""
    return _compare_keys(_version_key(left), _version_key(right))


def normalize_collector_release(raw: Any) -> Optional[Dict[str, Any]]:
    """把 wire 格式的 collector_release 块规范化成扁平字段。

    - `None` -> `None`（采集端没报版本，降级，不抛错）
    - 非对象 / 未知 key / 不合法值 -> `VersionContractError`
    - 缺字段 -> 该字段为 `None`，其余字段照常保留
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise VersionContractError(
            f"{COLLECTOR_RELEASE_FIELD} must be an object",
            field=COLLECTOR_RELEASE_FIELD,
        )

    for key in raw:
        if key not in COLLECTOR_RELEASE_WIRE_FIELDS:
            raise VersionContractError(
                f"{COLLECTOR_RELEASE_FIELD} does not accept unknown field: {key}",
                field=f"{COLLECTOR_RELEASE_FIELD}.{key}",
            )

    normalized: Dict[str, Any] = {field: None for field in COLLECTOR_VERSION_FIELDS}
    normalized["collector_version"] = _semver_or_none(
        raw.get("collector_version"), f"{COLLECTOR_RELEASE_FIELD}.collector_version"
    )
    normalized["config_schema_version"] = _schema_version_or_none(
        raw.get("config_schema_version"), f"{COLLECTOR_RELEASE_FIELD}.config_schema_version"
    )
    normalized["parser_schema_version"] = _schema_version_or_none(
        raw.get("parser_schema_version"), f"{COLLECTOR_RELEASE_FIELD}.parser_schema_version"
    )
    normalized["release_channel"] = _enum_or_none(
        raw.get("release_channel"), RELEASE_CHANNELS, f"{COLLECTOR_RELEASE_FIELD}.release_channel"
    )
    normalized["build_sha"] = _pattern_or_none(
        raw.get("build_sha"), _BUILD_SHA_RE, f"{COLLECTOR_RELEASE_FIELD}.build_sha"
    )

    last_upgrade = raw.get("last_upgrade")
    if last_upgrade is not None:
        if not isinstance(last_upgrade, dict):
            raise VersionContractError(
                f"{COLLECTOR_RELEASE_FIELD}.last_upgrade must be an object",
                field=f"{COLLECTOR_RELEASE_FIELD}.last_upgrade",
            )
        for key in last_upgrade:
            if key not in COLLECTOR_RELEASE_LAST_UPGRADE_FIELDS:
                raise VersionContractError(
                    f"{COLLECTOR_RELEASE_FIELD}.last_upgrade does not accept unknown field: {key}",
                    field=f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.{key}",
                )
        normalized["last_upgrade_status"] = _enum_or_none(
            last_upgrade.get("status"),
            LAST_UPGRADE_STATUSES,
            f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.status",
        )
        normalized["last_upgrade_from_version"] = _semver_or_none(
            last_upgrade.get("from_version"),
            f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.from_version",
        )
        normalized["last_upgrade_to_version"] = _semver_or_none(
            last_upgrade.get("to_version"),
            f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.to_version",
        )
        normalized["last_upgrade_finished_at"] = _pattern_or_none(
            last_upgrade.get("finished_at"),
            _TIMESTAMP_RE,
            f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.finished_at",
        )
    return normalized


def evaluate_collector_release(
    release: Optional[Dict[str, Any]],
    *,
    policy: Optional[VersionPolicy] = None,
) -> Dict[str, Any]:
    """判定采集端版本状态。

    判定优先级：`unsupported` > `rollback_available` > `update_available` > `current`。
    版本未知时返回 `unknown`：既不拒绝，也**不当成合规**（`verified` 为 False）。
    """
    active = policy or DEFAULT_VERSION_POLICY
    result: Dict[str, Any] = {field: None for field in COLLECTOR_VERSION_FIELDS}
    if release:
        result.update({key: release.get(key) for key in COLLECTOR_VERSION_FIELDS})
    result["min_supported_collector_version"] = active.min_supported_collector_version
    result["target_collector_version"] = active.target_collector_version
    result["rollback_target_version"] = None

    if release is None:
        return _finish(result, VERSION_STATE_UNKNOWN, "collector_release_missing", verified=False)

    collector_version = result["collector_version"]
    if not collector_version:
        return _finish(result, VERSION_STATE_UNKNOWN, "collector_version_missing", verified=False)

    if compare_versions(collector_version, active.min_supported_collector_version) < 0:
        return _finish(result, VERSION_STATE_UNSUPPORTED, "collector_version_below_minimum")

    config_schema_version = result["config_schema_version"]
    if config_schema_version is not None and config_schema_version < active.min_supported_config_schema_version:
        return _finish(result, VERSION_STATE_UNSUPPORTED, "config_schema_version_below_minimum")

    parser_schema_version = result["parser_schema_version"]
    if parser_schema_version is not None and parser_schema_version < active.min_supported_parser_schema_version:
        return _finish(result, VERSION_STATE_UNSUPPORTED, "parser_schema_version_below_minimum")

    if result["last_upgrade_status"] == "failed" and result["last_upgrade_from_version"]:
        result["rollback_target_version"] = result["last_upgrade_from_version"]
        return _finish(result, VERSION_STATE_ROLLBACK_AVAILABLE, "last_upgrade_failed")

    target_delta = compare_versions(collector_version, active.target_collector_version)
    if target_delta > 0:
        result["rollback_target_version"] = active.target_collector_version
        return _finish(result, VERSION_STATE_ROLLBACK_AVAILABLE, "collector_version_ahead_of_target")
    if target_delta < 0:
        return _finish(result, VERSION_STATE_UPDATE_AVAILABLE, "collector_version_behind_target")
    return _finish(result, VERSION_STATE_CURRENT, "collector_version_current")


def server_version_block(policy: Optional[VersionPolicy] = None) -> Dict[str, Any]:
    """服务端自身的版本与兼容策略，用于诊断页和 /api/health。"""
    active = policy or DEFAULT_VERSION_POLICY
    return {
        "api_version": SERVER_API_VERSION,
        "read_model_version": SERVER_READ_MODEL_VERSION,
        "ingest_schema_version": SERVER_INGEST_SCHEMA_VERSION,
        "min_supported_collector_version": active.min_supported_collector_version,
        "target_collector_version": active.target_collector_version,
    }


def build_version_health(
    source_status: Iterable[Dict[str, Any]],
    *,
    policy: Optional[VersionPolicy] = None,
) -> Dict[str, Any]:
    """汇总所有来源的版本状态，列出全部落后或不兼容设备。

    `needs_attention` 按 (状态严重度, source_id) 确定性排序，与输入顺序无关。
    """
    counts = {state: 0 for state in ALL_VERSION_STATES}
    needs_attention: List[Dict[str, Any]] = []
    for entry in source_status or []:
        if not isinstance(entry, dict):
            continue
        version = entry.get("version") if isinstance(entry.get("version"), dict) else {}
        state = str(version.get("state") or VERSION_STATE_UNKNOWN)
        if state not in counts:
            state = VERSION_STATE_UNKNOWN
        counts[state] += 1
        if state == VERSION_STATE_CURRENT:
            continue
        needs_attention.append(
            {
                "source_id": str(entry.get("source_id") or ""),
                "display_name": str(entry.get("display_name") or entry.get("source_id") or ""),
                "machine": entry.get("machine"),
                "os_user": entry.get("os_user"),
                "status": entry.get("status"),
                "observed_at": entry.get("observed_at"),
                "state": state,
                "collector_version": version.get("collector_version"),
                "release_channel": version.get("release_channel"),
                "build_sha": version.get("build_sha"),
                "reason": version.get("reason"),
                "compatible": bool(version.get("compatible", state != VERSION_STATE_UNSUPPORTED)),
            }
        )
    needs_attention.sort(key=lambda row: (VERSION_STATE_SEVERITY[row["state"]], row["source_id"]))
    return {
        "server": server_version_block(policy),
        "counts": counts,
        "needs_attention": needs_attention,
    }


def local_collector_release(
    *,
    config_schema_version: int,
    release_channel: Optional[str] = None,
    build_sha: Optional[str] = None,
    last_upgrade: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造本机采集端要上报的 wire 版本块，出站前先自校验一次。"""
    block: Dict[str, Any] = {
        "collector_version": COLLECTOR_VERSION,
        "config_schema_version": int(config_schema_version),
        "parser_schema_version": COLLECTOR_PARSER_SCHEMA_VERSION,
        "release_channel": release_channel or DEFAULT_RELEASE_CHANNEL,
        "last_upgrade": dict(last_upgrade) if last_upgrade else {"status": "never"},
    }
    if build_sha:
        block["build_sha"] = build_sha
    normalize_collector_release(block)
    return block


# --- 内部工具 ---------------------------------------------------------------


def _finish(result: Dict[str, Any], state: str, reason: str, *, verified: bool = True) -> Dict[str, Any]:
    result["state"] = state
    result["reason"] = reason
    result["compatible"] = state != VERSION_STATE_UNSUPPORTED
    result["accepted"] = state != VERSION_STATE_UNSUPPORTED
    result["verified"] = verified
    return result


def _version_key(value: str) -> tuple:
    text = str(value or "")
    core, _, suffix = text.partition("-")
    core = core.partition("+")[0]
    parts = []
    for chunk in core.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return (tuple(parts[:3]), 1 if not suffix else 0, suffix)


def _compare_keys(left: tuple, right: tuple) -> int:
    if left[0] != right[0]:
        return 1 if left[0] > right[0] else -1
    if left[1] != right[1]:
        return 1 if left[1] > right[1] else -1
    if left[2] != right[2]:
        return 1 if left[2] > right[2] else -1
    return 0


def _semver_or_none(value: Any, field: str) -> Optional[str]:
    return _pattern_or_none(value, _SEMVER_RE, field)


def _pattern_or_none(value: Any, pattern: "re.Pattern[str]", field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not pattern.match(value):
        raise VersionContractError(f"{field} is not a valid version field value (value omitted)", field=field)
    return value


def _enum_or_none(value: Any, allowed: tuple, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise VersionContractError(
            f"{field} must be one of: {', '.join(allowed)} (value omitted)",
            field=field,
        )
    return value


def _schema_version_or_none(value: Any, field: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise VersionContractError(f"{field} must be an integer (value omitted)", field=field)
    if value < 0 or value > _MAX_SCHEMA_VERSION:
        raise VersionContractError(f"{field} is out of the accepted range (value omitted)", field=field)
    return value
