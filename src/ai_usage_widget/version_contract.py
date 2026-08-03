"""版本合同——**采集端自报半边**。

#74 拆分（#67 裁决清单第 4 条）：服务端判定权威（四态词表、compareVersions、
wire 校验与脱敏的服务端入口、兼容策略、版本健康读模型）在
`cloudflare/native-worker/src/version-contract.ts`。本模块只保留设备侧需要的部分：
构造并自检本机上报的 `collector_release` wire 块（`pusher.py`）、
发布通道枚举（`config.py`）、服务端拒收时的错误类型常量（outbox 分类用）。

两侧 wire 口径不漂移由跨实现合同 fixture 兜底：`collector_payload_fixture.json`
含 `collector_release` 块，`ingest.test.ts` 逐字段断言 Worker 声明并解析它。

安全边界：所有版本字段都用**收紧的字面量白名单**校验（semver / 十六进制 SHA /
枚举 / ISO 时间戳）。token、绝对路径、命令行参数等形态无法通过校验，
因此不可能出现在出站版本块里。校验失败的异常信息**只报字段名，不回显值**。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# --- 采集端本机版本常量 ------------------------------------------------------

COLLECTOR_VERSION = "0.3.0"
COLLECTOR_PARSER_SCHEMA_VERSION = 2
DEFAULT_RELEASE_CHANNEL = "stable"
RELEASE_CHANNELS = ("stable", "beta", "dev")
LAST_UPGRADE_STATUSES = ("never", "succeeded", "failed", "rolled_back")

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

#: 服务端判定「明确不兼容」后返回的错误类型（权威在 version-contract.ts）。
#: 采集端用它对上报失败做 outbox 分类：不兼容属于「升级前重试无意义」。
UNSUPPORTED_ERROR_TYPE = "collector_version_unsupported"

# --- 校验用字面量白名单 ------------------------------------------------------

_SEMVER_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][0-9A-Za-z][0-9A-Za-z.]{0,31})?$")
_BUILD_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_SCHEMA_VERSION = 10000
#: 只有形态明确安全的 key 名才会出现在错误信息里；其余一律脱敏。
#: JSON key 是完全不受控的任意文本，直接回显等于把疑似凭据写进 HTTP 响应和日志。
#:
#: 这里只放行「普通 snake_case 字段名」形态：纯小写字母分段、单段不超过 16 字符、
#: 总长不超过 32。大小写混排、含数字、超长单段（AWS Access Key ID、Slack token、
#: 十六进制密钥等凭据形态）一律脱敏——回显不了字段名只是排障体验降级，
#: 回显了凭据就是把秘密写进 400 响应体和服务端日志。
_SAFE_KEY_RE = re.compile(r"[a-z]{1,16}(?:_[a-z]{1,16})*")
_MAX_SAFE_KEY_LENGTH = 32
_REDACTED_KEY = "<redacted>"


class VersionContractError(ValueError):
    """版本字段不符合合同。异常信息只包含字段名，不回显字段值。"""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


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
            safe_key = _safe_key(key)
            raise VersionContractError(
                f"{COLLECTOR_RELEASE_FIELD} does not accept unknown field: {safe_key}",
                field=f"{COLLECTOR_RELEASE_FIELD}.{safe_key}",
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
                safe_key = _safe_key(key)
                raise VersionContractError(
                    f"{COLLECTOR_RELEASE_FIELD}.last_upgrade does not accept unknown field: {safe_key}",
                    field=f"{COLLECTOR_RELEASE_FIELD}.last_upgrade.{safe_key}",
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


def local_collector_release(
    *,
    config_schema_version: Optional[int] = None,
    release_channel: Optional[str] = None,
    build_sha: Optional[str] = None,
    last_upgrade: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造本机采集端要上报的 wire 版本块，出站前先自校验一次。

    不传 `config_schema_version` 就不带这个字段：版本块里只有代码常量，
    永远合法，可以作为采集端的最后兜底。
    """
    block: Dict[str, Any] = {
        "collector_version": COLLECTOR_VERSION,
        "parser_schema_version": COLLECTOR_PARSER_SCHEMA_VERSION,
        "release_channel": release_channel or DEFAULT_RELEASE_CHANNEL,
        "last_upgrade": dict(last_upgrade) if last_upgrade else {"status": "never"},
    }
    if config_schema_version is not None:
        block["config_schema_version"] = int(config_schema_version)
    if build_sha:
        block["build_sha"] = build_sha
    normalize_collector_release(block)
    return block


# --- 内部工具 ---------------------------------------------------------------


def _safe_key(key: Any) -> str:
    text = str(key)
    if len(text) > _MAX_SAFE_KEY_LENGTH or not _SAFE_KEY_RE.fullmatch(text):
        return _REDACTED_KEY
    return text


def _semver_or_none(value: Any, field: str) -> Optional[str]:
    return _pattern_or_none(value, _SEMVER_RE, field)


def _pattern_or_none(value: Any, pattern: "re.Pattern[str]", field: str) -> Optional[str]:
    if value is None:
        return None
    # 必须用 fullmatch：`re.match` + `$` 会在末尾单个 `\n` 之前匹配，
    # 带换行的版本号能穿过白名单、原样落库并裂成第二个字符串。
    if not isinstance(value, str) or not pattern.fullmatch(value):
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
