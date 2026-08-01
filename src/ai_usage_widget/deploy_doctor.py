"""采集端部署预检 doctor（Issue #57）。

产品目标：新设备部署失败时，用户第一眼就知道**该做什么**，而不是反复猜测
「是不是 token 过期了」。为此 doctor 对八类部署问题各给一个唯一的
机器可读 reason code，并按「用户下一步动作」把 reason code 归到退出码类别。

硬约束：

- **全程只读。** 不写配置、不写库、不改 systemd 单元，只做检查。
- **不打印凭据。** 报告里只出现 token 的环境变量名和是否存在，
  URL 里的 userinfo 一律脱敏，探测响应体和响应头都不进报告。
- **可离线重放。** 所有外部事实（HTTP 探测、systemctl、身份、时区）都先落成
  `DoctorEnvironment` 这个纯数据结构，`diagnose()` 是纯函数。
"""

from __future__ import annotations

import getpass
import json
import os
import shlex
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import ConfigError, normalize_platform
from .http_identity import PRODUCT_USER_AGENT
from .timezones import get_timezone


REASON_OK = "ok"

REASON_ENTRY_BLOCKED_BY_WAF = "entry_blocked_by_waf"
REASON_AUTH_TOKEN_INVALID = "auth_token_invalid"
REASON_NETWORK_UNREACHABLE = "network_unreachable"
REASON_TIMEZONE_MISMATCH = "timezone_mismatch"
REASON_DEVICE_IDENTITY_MISMATCH = "device_identity_mismatch"
REASON_RUNTIME_RELEASE_UNVERSIONED = "runtime_release_unversioned"
REASON_PYTHONPATH_IMPORT_MISMATCH = "pythonpath_import_mismatch"
REASON_TIMER_WITHOUT_FUTURE_TRIGGER = "timer_without_future_trigger"

#: Issue #57 要求互相区分的八类部署问题，顺序即检查顺序里的严重度顺序。
#: **这八个必须保持一一对应、互不相同**，新增情况一律进 ADDITIONAL_REASON_CODES。
DIAGNOSTIC_REASON_CODES: Tuple[str, ...] = (
    REASON_NETWORK_UNREACHABLE,
    REASON_ENTRY_BLOCKED_BY_WAF,
    REASON_AUTH_TOKEN_INVALID,
    REASON_DEVICE_IDENTITY_MISMATCH,
    REASON_TIMEZONE_MISMATCH,
    REASON_RUNTIME_RELEASE_UNVERSIONED,
    REASON_PYTHONPATH_IMPORT_MISMATCH,
    REASON_TIMER_WITHOUT_FUTURE_TRIGGER,
)

#: 入口被门户 / IdP 302 接管。补救动作和 WAF 拦截同一类（放行入口，别动 token），
#: 但必须能机器区分，否则操作者看不出「我根本没连到自家 origin」。
REASON_ENTRY_REDIRECTED_TO_PORTAL = "entry_redirected_to_portal"
#: 收到了完整 HTTP 响应，但它不是本产品的 /api/health 契约（404 / 5xx / 被接管的 200）。
#: 网络明明是通的，不能报成 network_unreachable 把用户引去查一个没问题的 DNS。
REASON_ENTRY_ROUTE_UNEXPECTED = "entry_route_unexpected"
#: 事实没采到：既不是通过也不是失败。宁可明确说不知道，也不假绿。
REASON_PRECHECK_INCOMPLETE = "precheck_incomplete"

ADDITIONAL_REASON_CODES: Tuple[str, ...] = (
    REASON_ENTRY_REDIRECTED_TO_PORTAL,
    REASON_ENTRY_ROUTE_UNEXPECTED,
    REASON_PRECHECK_INCOMPLETE,
)

ALL_REASON_CODES: Tuple[str, ...] = DIAGNOSTIC_REASON_CODES + ADDITIONAL_REASON_CODES

CATEGORY_OK = "ok"
CATEGORY_NETWORK = "network"
CATEGORY_ENTRY_GUARD = "entry_guard"
CATEGORY_AUTH = "auth"
CATEGORY_IDENTITY = "identity"
CATEGORY_RUNTIME = "runtime"
CATEGORY_SCHEDULE = "schedule"
CATEGORY_ORIGIN = "origin"
CATEGORY_INCOMPLETE = "incomplete"

REASON_CATEGORIES: Dict[str, str] = {
    REASON_OK: CATEGORY_OK,
    REASON_NETWORK_UNREACHABLE: CATEGORY_NETWORK,
    REASON_ENTRY_BLOCKED_BY_WAF: CATEGORY_ENTRY_GUARD,
    REASON_ENTRY_REDIRECTED_TO_PORTAL: CATEGORY_ENTRY_GUARD,
    REASON_AUTH_TOKEN_INVALID: CATEGORY_AUTH,
    REASON_DEVICE_IDENTITY_MISMATCH: CATEGORY_IDENTITY,
    REASON_TIMEZONE_MISMATCH: CATEGORY_IDENTITY,
    REASON_RUNTIME_RELEASE_UNVERSIONED: CATEGORY_RUNTIME,
    REASON_PYTHONPATH_IMPORT_MISMATCH: CATEGORY_RUNTIME,
    REASON_TIMER_WITHOUT_FUTURE_TRIGGER: CATEGORY_SCHEDULE,
    REASON_ENTRY_ROUTE_UNEXPECTED: CATEGORY_ORIGIN,
    REASON_PRECHECK_INCOMPLETE: CATEGORY_INCOMPLETE,
}

#: 退出码按「用户下一步动作」分组。入口拦截 (12) 与 token 无效 (13) 必须分开：
#: 这正是 Issue #57 里「避免错误引导用户轮换 token」那一条。
CATEGORY_EXIT_CODES: Dict[str, int] = {
    CATEGORY_OK: 0,
    CATEGORY_NETWORK: 11,
    CATEGORY_ENTRY_GUARD: 12,
    CATEGORY_AUTH: 13,
    CATEGORY_IDENTITY: 14,
    CATEGORY_RUNTIME: 15,
    CATEGORY_SCHEDULE: 16,
    CATEGORY_ORIGIN: 17,
    CATEGORY_INCOMPLETE: 18,
}

#: 单项检查的四态。`ok` 之外还要区分 unknown（事实没采到）和 skipped（本次不适用）。
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_SKIPPED = "skipped"

#: doctor 自身跑不起来（配置读不出来等），既不是体检通过也不属于八类之一。
EXIT_DOCTOR_ERROR = 1


class DoctorPreconditionError(ValueError):
    """doctor 跑不起来的前置失败。

    消息全部由代码写死，只含配置路径和字段名，**不含配置内容或凭据**，
    因此可以安全地直接输出给用户——说不出哪里错的诊断等于没诊断。
    """


TIMER_SCOPE_USER = "user"
TIMER_SCOPE_SYSTEM = "system"
TIMER_SCOPES = (TIMER_SCOPE_USER, TIMER_SCOPE_SYSTEM)

_NO_TRIGGER_SENTINELS = {"", "n/a", "0", "infinity", "-"}
_ENABLED_UNIT_STATES = {"enabled", "enabled-runtime", "static", "generated", "linked"}
_WAF_BODY_MARKERS = (
    "attention required",
    "cloudflare ray id",
    "you have been blocked",
    "error 1020",
    "access denied",
)


def category_for_reason(reason_code: str) -> str:
    if reason_code == REASON_OK:
        return CATEGORY_OK
    return REASON_CATEGORIES.get(reason_code, CATEGORY_RUNTIME)


def exit_code_for_reason(reason_code: str) -> int:
    if reason_code == REASON_OK:
        return 0
    if reason_code not in REASON_CATEGORIES:
        return EXIT_DOCTOR_ERROR
    return CATEGORY_EXIT_CODES[REASON_CATEGORIES[reason_code]]


# --------------------------------------------------------------------------- #
# 事实数据结构（可由离线 fixture 直接构造）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntryProbe:
    """一次只读入口探测的结果。响应体和响应头只用于判定，不进报告。"""

    url: str = ""
    status: Optional[int] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str = ""
    error: Optional[str] = None
    #: 是否发生了重定向。探测不跟随重定向，这里只是把事实记下来，
    #: 否则操作者根本看不出自己连的其实不是自家 origin。
    redirected: bool = False
    redirect_location: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "EntryProbe":
        data = data or {}
        headers = data.get("headers") or {}
        return cls(
            url=str(data.get("url") or ""),
            status=int(data["status"]) if data.get("status") is not None else None,
            headers={str(key).lower(): str(value) for key, value in dict(headers).items()},
            body=str(data.get("body") or ""),
            error=str(data["error"]) if data.get("error") else None,
            redirected=bool(data.get("redirected")),
            redirect_location=str(data.get("redirect_location") or ""),
        )


@dataclass(frozen=True)
class DoctorEnvironment:
    """doctor 判定所需的全部事实。采集与判定分离，判定是纯函数。"""

    device_config: Mapping[str, Any] = field(default_factory=dict)
    entry_probe: EntryProbe = field(default_factory=EntryProbe)
    token_env: Optional[str] = None
    token_present: bool = False
    system_timezone: Optional[str] = None
    observed_identity: Mapping[str, str] = field(default_factory=dict)
    release_dir: Optional[str] = None
    release_manifest: Optional[Mapping[str, Any]] = None
    python_path: Sequence[str] = ()
    imported_from: Optional[str] = None
    #: timer 对应 service unit 里的 `Environment=`。这才是 Issue 里出事故的那一份
    #: PYTHONPATH；`None` 表示没采到（未知），`{}` 表示 unit 确实没设环境变量。
    unit_environment: Optional[Mapping[str, str]] = None
    #: unit PYTHONPATH 里真正含有可导入 ai_usage_widget 的目录（只读探测得到）。
    unit_pythonpath_package_roots: Sequence[str] = ()
    timer_unit: Optional[str] = None
    timer_properties: Mapping[str, str] = field(default_factory=dict)
    #: systemd manager 作用域：BIAI 现网采集 timer 是 system-level 的。
    timer_scope: str = TIMER_SCOPE_USER
    #: 本平台是否支持当前的 timer 检查实现（只实现了 systemd；macOS launchd 未实现）。
    timer_supported: bool = True
    reference_time: Optional[str] = None
    #: 本次运行中已知的凭据值，仅用于输出前遮蔽，绝不进入报告。
    secret_values: Tuple[str, ...] = ()

    @classmethod
    def from_fixture(cls, data: Mapping[str, Any]) -> "DoctorEnvironment":
        device_config = dict(data.get("device_config") or {})
        release = dict(data.get("release") or {})
        timer = dict(data.get("timer") or {})
        timer_properties = timer.get("properties")
        if timer_properties is None and timer.get("show_output") is not None:
            timer_properties = parse_systemctl_show(str(timer.get("show_output")))
        return cls(
            device_config=device_config,
            entry_probe=EntryProbe.from_dict(data.get("entry_probe")),
            token_env=device_config.get("token_env"),
            token_present=bool(data.get("token_present")),
            system_timezone=data.get("system_timezone"),
            observed_identity={
                str(key): str(value)
                for key, value in dict(data.get("observed_identity") or {}).items()
            },
            release_dir=release.get("path"),
            release_manifest=release.get("manifest"),
            python_path=[str(item) for item in (data.get("python_path") or [])],
            imported_from=data.get("imported_from"),
            unit_environment=(
                {str(key): str(value) for key, value in dict(data["unit_environment"]).items()}
                if isinstance(data.get("unit_environment"), dict)
                else None
            ),
            unit_pythonpath_package_roots=[
                str(item) for item in (data.get("unit_pythonpath_package_roots") or [])
            ],
            timer_unit=timer.get("unit"),
            timer_properties=dict(timer_properties or {}),
            timer_scope=str(timer.get("scope") or TIMER_SCOPE_USER),
            timer_supported=bool(timer.get("supported", True)),
            reference_time=data.get("reference_time"),
            secret_values=tuple(str(item) for item in (data.get("secret_values") or [])),
        )


SECRET_MASK = "***"
_MIN_MASKABLE_SECRET_LENGTH = 4


def mask_secrets(text: str, secret_values: Sequence[str]) -> str:
    """把已知凭据值换成掩码。太短的值不遮蔽，避免把正常文本打成马赛克。"""

    masked = text
    for secret in secret_values:
        secret = str(secret or "")
        if len(secret) < _MIN_MASKABLE_SECRET_LENGTH:
            continue
        masked = masked.replace(secret, SECRET_MASK)
    return masked


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    reason_code: str
    detail: str
    remediation: str = ""
    #: 四态之一：ok / failed / unknown / skipped。不传时按 ok 推导。
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            object.__setattr__(self, "status", STATUS_OK if self.ok else STATUS_FAILED)

    def to_dict(self, secret_values: Sequence[str] = ()) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "reason_code": self.reason_code,
            "category": category_for_reason(self.reason_code),
            "detail": mask_secrets(self.detail, secret_values),
            "remediation": mask_secrets(self.remediation, secret_values),
        }


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    reason_code: str
    exit_code: int
    checks: Tuple[DoctorCheck, ...]
    #: 已知凭据值。只用于 `to_dict()` 前的遮蔽，本身永远不序列化。
    secret_values: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doctor": "deploy",
            "ok": self.ok,
            "reason_code": self.reason_code,
            "category": category_for_reason(self.reason_code),
            "exit_code": self.exit_code,
            "failed_reason_codes": [
                check.reason_code for check in self.checks if check.status == STATUS_FAILED
            ],
            "unknown_checks": [
                check.name for check in self.checks if check.status == STATUS_UNKNOWN
            ],
            "skipped_checks": [
                check.name for check in self.checks if check.status == STATUS_SKIPPED
            ],
            "checks": [check.to_dict(self.secret_values) for check in self.checks],
        }


# --------------------------------------------------------------------------- #
# systemd timer 事实解析
# --------------------------------------------------------------------------- #


def parse_systemctl_show(text: str) -> Dict[str, str]:
    """解析 `systemctl show <unit> --property=...` 的 KEY=VALUE 输出。"""

    properties: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        properties[key.strip()] = value.strip()
    return properties


def has_future_trigger(properties: Mapping[str, str]) -> bool:
    """systemd 把「没有下一次触发」表示为 NextElapse* 为 n/a / 0 / infinity。"""

    for key in ("NextElapseUSecRealtime", "NextElapseUSecMonotonic"):
        value = str(properties.get(key, "")).strip().casefold()
        if value and value not in _NO_TRIGGER_SENTINELS:
            return True
    return False


def is_unit_enabled(properties: Mapping[str, str]) -> bool:
    return str(properties.get("UnitFileState", "")).strip().casefold() in _ENABLED_UNIT_STATES


# --------------------------------------------------------------------------- #
# 判定（纯函数）
# --------------------------------------------------------------------------- #


def _ok(name: str, detail: str) -> DoctorCheck:
    return DoctorCheck(name=name, ok=True, reason_code=REASON_OK, detail=detail)


def _fail(name: str, reason_code: str, detail: str, remediation: str) -> DoctorCheck:
    return DoctorCheck(
        name=name,
        ok=False,
        reason_code=reason_code,
        detail=detail,
        remediation=remediation,
        status=STATUS_FAILED,
    )


def _unknown(name: str, detail: str, remediation: str) -> DoctorCheck:
    """事实没采到。不算通过（ok=False），但也不冒充某一类具体故障。"""

    return DoctorCheck(
        name=name,
        ok=False,
        reason_code=REASON_PRECHECK_INCOMPLETE,
        detail=detail,
        remediation=remediation,
        status=STATUS_UNKNOWN,
    )


def _skipped(name: str, detail: str) -> DoctorCheck:
    """本次运行不适用（例如没指定 timer 单元），不影响整体结论。"""

    return DoctorCheck(
        name=name,
        ok=True,
        reason_code=REASON_OK,
        detail=detail,
        status=STATUS_SKIPPED,
    )


def redact_url(url: str) -> str:
    """去掉 URL 里的 userinfo（可能含口令）与 query（可能含 token）。"""

    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparsable-url>"
    if not parsed.scheme or not parsed.netloc:
        return "<unparsable-url>"
    try:
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "<unparsable-url>"
    if port:
        host = f"{host}:{port}"
    if parsed.username or parsed.password:
        host = f"<redacted>@{host}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _looks_like_entry_guard(probe: EntryProbe) -> bool:
    status = probe.status
    body = (probe.body or "").casefold()
    headers = {key.casefold(): str(value).casefold() for key, value in probe.headers.items()}
    if status == 403:
        return True
    if "cf-mitigated" in headers:
        return True
    if status is not None and status >= 400:
        if any(marker in body for marker in _WAF_BODY_MARKERS):
            return True
        if headers.get("server") == "cloudflare" and status in {
            429, 503, 520, 521, 522, 523, 524, 525, 526, 527,
        }:
            return True
    return False


def _check_entry(environment: DoctorEnvironment) -> DoctorCheck:
    probe = environment.entry_probe
    target = redact_url(probe.url) or redact_url(str(environment.device_config.get("server_url") or ""))
    if probe.error or probe.status is None:
        return _fail(
            "entry_reachability",
            REASON_NETWORK_UNREACHABLE,
            f"入口 {target} 无法建立连接（{probe.error or 'no_response'}）",
            "先确认设备出网、DNS 与代理，再谈 token；不要轮换凭据。",
        )
    if probe.redirected:
        # 探测不跟随重定向，所以 token 没有被带到下一跳。
        return _fail(
            "entry_reachability",
            REASON_ENTRY_REDIRECTED_TO_PORTAL,
            f"入口 {target} 返回 {probe.status} 重定向到 {redact_url(probe.redirect_location)}，"
            "请求被门户 / IdP 接管，根本没到本产品 origin",
            "放行采集端到 /api/health 与 /ingest 的直连（或给它单独的服务令牌通道）；"
            "不要轮换 ingest token，探测已阻止把它发给重定向目标。",
        )
    if _looks_like_entry_guard(probe):
        return _fail(
            "entry_reachability",
            REASON_ENTRY_BLOCKED_BY_WAF,
            f"入口 {target} 返回 {probe.status}，特征是入口防护/WAF 拦截而不是认证失败",
            "放行采集端的产品请求身份（User-Agent / 来源 IP），不要轮换 token。",
        )
    if probe.status in {401, 407}:
        token_hint = "已提供 token" if environment.token_present else "未提供 token"
        return _fail(
            "entry_reachability",
            REASON_AUTH_TOKEN_INVALID,
            f"入口 {target} 返回 {probe.status}，{token_hint}但被拒绝",
            f"检查环境变量 {environment.token_env or '<未配置>'} 里的 ingest token 是否有效。",
        )
    if probe.status == 200 and looks_like_health_payload(probe.body):
        return _ok("entry_reachability", f"入口 {target} 返回了本产品的 /api/health 响应（200）")
    if probe.status == 200:
        return _fail(
            "entry_reachability",
            REASON_ENTRY_ROUTE_UNEXPECTED,
            f"入口 {target} 返回 200，但响应体不是本产品的 /api/health 契约"
            "（缺 status=ok 或 backend_mode）",
            "确认域名/路由指向本产品 origin；若被登录门户就地接管，先放行采集端请求身份。",
        )
    return _fail(
        "entry_reachability",
        REASON_ENTRY_ROUTE_UNEXPECTED,
        f"入口 {target} 返回 {probe.status}，网络是通的但这不是本产品的 /api/health 响应",
        "查域名解析目标、入口路由与 origin 服务状态；这既不是网络不通，也不是 token 问题。",
    )


def looks_like_health_payload(body: str) -> bool:
    """确认这确实是本产品 `/api/health` 的响应，而不是随便一个 200。

    origin (`server_services.build_health_response`) 与 Cloudflare Worker
    (`buildHealthResponse`) 两侧都返回 `status: "ok"` + `backend_mode`，
    这是跨实现的共同契约。captive portal / IdP 登录页给不出这个形状。
    """

    try:
        data = json.loads(body or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return str(data.get("status")) == "ok" and bool(data.get("backend_mode"))


def _check_device_identity(environment: DoctorEnvironment) -> DoctorCheck:
    config = environment.device_config
    observed = environment.observed_identity or {}
    # machine 可以缺省：config.py 的 owner 口径会兜底成本机主机名。
    # os_user 则必须显式写对，跨 OS 用户采集会直接污染归属。
    missing = [
        key
        for key in ("source_id", "os_user", "platform")
        if not config.get(key) or str(config.get(key)).strip().lower() == "unknown"
    ]
    if missing:
        return _fail(
            "device_identity",
            REASON_DEVICE_IDENTITY_MISMATCH,
            f"设备身份缺失字段: {', '.join(sorted(missing))}",
            "补齐设备配置里的 source_id / os_user / platform。",
        )
    try:
        configured_platform = normalize_platform(config.get("platform"))
    except ConfigError as exc:
        return _fail(
            "device_identity",
            REASON_DEVICE_IDENTITY_MISMATCH,
            f"设备身份 platform 不受支持: {exc}",
            "platform 只能是 darwin(mac) / linux / windows。",
        )
    configured = {
        "machine": config.get("machine") or observed.get("machine"),
        "os_user": config.get("os_user"),
        "platform": configured_platform,
    }
    differences: List[str] = []
    for key in ("machine", "os_user", "platform"):
        actual = observed.get(key)
        if actual and str(configured.get(key)) != str(actual):
            differences.append(f"{key}: 配置={configured.get(key)} 实际={actual}")
    if differences:
        return _fail(
            "device_identity",
            REASON_DEVICE_IDENTITY_MISMATCH,
            "设备身份与本机实际不一致（" + "；".join(differences) + "）",
            "每个 OS 用户只在自己的账户上下文采集，把配置改成本机实际身份。",
        )
    return _ok("device_identity", f"设备身份一致（source_id={config.get('source_id')}）")


def _reference_datetime(environment: DoctorEnvironment) -> datetime:
    if environment.reference_time:
        try:
            return datetime.fromisoformat(str(environment.reference_time).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(dt_timezone.utc)


def _check_timezone(environment: DoctorEnvironment) -> DoctorCheck:
    configured = environment.device_config.get("timezone")
    if not configured:
        return _fail(
            "timezone_alignment",
            REASON_TIMEZONE_MISMATCH,
            "设备配置没有 timezone，本机与远程采集无法显式对齐时区",
            "在设备配置里显式写明 timezone。",
        )
    system = environment.system_timezone
    if not system:
        return _ok("timezone_alignment", f"配置时区 {configured}，本机时区未知，跳过比对")
    if str(system) == str(configured):
        return _ok("timezone_alignment", f"配置时区与本机时区一致（{configured}）")

    reference = _reference_datetime(environment)
    try:
        configured_offset = reference.astimezone(get_timezone(str(configured))).utcoffset()
        system_offset = reference.astimezone(get_timezone(str(system))).utcoffset()
    except Exception as exc:
        return _fail(
            "timezone_alignment",
            REASON_TIMEZONE_MISMATCH,
            f"时区名无法解析（配置={configured} 本机={system} 错误={exc.__class__.__name__}）",
            "改成 IANA 时区名，例如 Asia/Shanghai。",
        )
    if configured_offset == system_offset:
        return _ok(
            "timezone_alignment",
            f"配置时区 {configured} 与本机 {system} 名称不同但偏移一致",
        )
    return _fail(
        "timezone_alignment",
        REASON_TIMEZONE_MISMATCH,
        f"时区不一致：配置={configured}({configured_offset}) 本机={system}({system_offset})",
        "把设备配置的 timezone 和本机系统时区对齐，否则日聚合会错位。",
    )


def _check_runtime_release(environment: DoctorEnvironment) -> DoctorCheck:
    if not environment.release_dir:
        return _fail(
            "runtime_release",
            REASON_RUNTIME_RELEASE_UNVERSIONED,
            "运行目录未知，无法确认部署的是哪一版代码",
            "用版本化 release 目录部署，禁止部署不可追溯的现场代码。",
        )
    manifest = environment.release_manifest or {}
    version = str(manifest.get("version") or "").strip()
    revision = str(manifest.get("revision") or "").strip()
    if not version or not revision:
        return _fail(
            "runtime_release",
            REASON_RUNTIME_RELEASE_UNVERSIONED,
            f"运行目录 {environment.release_dir} 没有版本信息（release.json 缺失或缺 version/revision）",
            "改用 release manifest 部署，让每次上报都能回溯到具体版本。",
        )
    return _ok("runtime_release", f"运行目录版本 {version}（revision={revision}）")


def _import_root(imported_from: str) -> Path:
    # imported_from 指向 ai_usage_widget/__init__.py，其上两级即导入根目录。
    return Path(imported_from).resolve().parent.parent


def _check_pythonpath(environment: DoctorEnvironment) -> DoctorCheck:
    """检查 **timer 那个 unit** 里的 PYTHONPATH，而不是操作者 shell 里的。

    Issue #57 的原始事故是 unit 里 `Environment=PYTHONPATH=` 指向了另一棵树；
    操作者手敲对了环境变量再跑 doctor，恰恰会把这个故障掩盖掉。
    """

    if environment.timer_unit:
        if environment.unit_environment is None:
            return _unknown(
                "pythonpath_alignment",
                f"没能读到 {environment.timer_unit} 对应 service 的 Environment，"
                "无法确认 unit 里的 PYTHONPATH",
                "确认能执行 systemctl show <service> --property=Environment（注意 --timer-scope）。",
            )
        return _check_unit_pythonpath(environment)

    # 没有 timer 单元可查时，退回到「本进程」这一层，并明确标注它只是弱检查。
    entries = [entry for entry in (environment.python_path or []) if entry]
    if not entries or not environment.imported_from:
        return _skipped(
            "pythonpath_alignment",
            "未指定 --timer-unit，无法检查 unit 里的 PYTHONPATH（本项未执行）",
        )
    actual_root = _import_root(str(environment.imported_from))
    declared = {Path(entry).resolve() for entry in entries}
    if actual_root in declared:
        return _ok(
            "pythonpath_alignment",
            f"当前进程 PYTHONPATH 与实际导入目录一致（{actual_root}）；"
            "unit 里的那一份未检查，需要 --timer-unit",
        )
    return _fail(
        "pythonpath_alignment",
        REASON_PYTHONPATH_IMPORT_MISMATCH,
        f"当前进程 PYTHONPATH={os.pathsep.join(entries)} 与实际导入目录 {actual_root} 不一致",
        "让 PYTHONPATH 指向真正被导入的 release 目录，否则改代码不会生效。",
    )


def _check_unit_pythonpath(environment: DoctorEnvironment) -> DoctorCheck:
    unit_environment = environment.unit_environment or {}
    raw = str(unit_environment.get("PYTHONPATH") or "")
    entries = [entry for entry in raw.split(os.pathsep) if entry]
    if not entries:
        return _ok(
            "pythonpath_alignment",
            f"{environment.timer_unit} 对应 service 未设置 PYTHONPATH，按已安装包导入",
        )

    package_roots = {Path(entry).resolve() for entry in environment.unit_pythonpath_package_roots}
    if not package_roots:
        return _fail(
            "pythonpath_alignment",
            REASON_PYTHONPATH_IMPORT_MISMATCH,
            f"unit PYTHONPATH={raw} 里没有一个目录含可导入的 ai_usage_widget，"
            "timer 跑起来会导入到别的副本或直接失败",
            "把 unit 的 Environment=PYTHONPATH 指向真正部署的 release src 目录。",
        )

    if environment.release_dir:
        expected = (Path(environment.release_dir) / "src").resolve()
        declared = {Path(entry).resolve() for entry in entries}
        if expected not in declared:
            return _fail(
                "pythonpath_alignment",
                REASON_PYTHONPATH_IMPORT_MISMATCH,
                f"unit PYTHONPATH={raw} 与部署的 release 目录 {expected} 不一致，"
                "timer 实际导入的不是本次部署的代码",
                "把 unit 的 Environment=PYTHONPATH 改成 <release>/src 后 daemon-reload。",
            )

    return _ok(
        "pythonpath_alignment",
        f"{environment.timer_unit} 对应 service 的 PYTHONPATH 指向可导入的部署目录（{raw}）",
    )


def _check_timer(environment: DoctorEnvironment) -> DoctorCheck:
    if not environment.timer_unit:
        return _skipped("timer_schedule", "未指定 --timer-unit，本项未执行")
    properties = environment.timer_properties or {}
    unit = environment.timer_unit
    scope = environment.timer_scope or TIMER_SCOPE_USER
    if not environment.timer_supported:
        # 本机是 Linux 开发机，没有 Mac 可验收，所以不假实现 launchd 分支。
        return _unknown(
            "timer_schedule",
            f"本平台的定时任务由 launchd 管理，doctor 尚未实现 launchd 检查，"
            f"{unit} 的未来触发未经验证",
            "在 Mac 侧用 launchctl print gui/$(id -u)/<label> 人工确认（需回 Mac 侧执行）。",
        )
    if not properties:
        return _unknown(
            "timer_schedule",
            f"在 {scope} scope 下没能读到 {unit} 的单元状态，无法判断它是否还会触发",
            f"确认 systemd {scope} manager 可访问；单元装在另一个 scope 时改用 --timer-scope。",
        )
    load_state = str(properties.get("LoadState", "")).strip().casefold()
    if load_state == "not-found":
        # 单元装在另一个 scope（BIAI 采集器是 system-level）时最常见，
        # 让用户先换 scope 再说重装，避免把健康 timer 拆掉重来。
        return _fail(
            "timer_schedule",
            REASON_TIMER_WITHOUT_FUTURE_TRIGGER,
            f"{scope} scope 下不存在单元 {unit}，该 scope 没有未来触发",
            f"先确认单元装在 user 还是 system scope（改用 --timer-scope），确实缺失再安装单元。",
        )
    if load_state and load_state != "loaded":
        return _fail(
            "timer_schedule",
            REASON_TIMER_WITHOUT_FUTURE_TRIGGER,
            f"{unit} 在 {scope} scope 下 LoadState={load_state}，单元未加载，不会再触发",
            "重新安装单元文件并 daemon-reload。",
        )
    if not is_unit_enabled(properties):
        return _fail(
            "timer_schedule",
            REASON_TIMER_WITHOUT_FUTURE_TRIGGER,
            f"{unit} 在 {scope} scope 下 UnitFileState="
            f"{properties.get('UnitFileState') or 'unknown'}，未启用，不会再触发",
            f"执行 systemctl --{scope} enable --now {unit} 后重新预检。",
        )
    if not has_future_trigger(properties):
        return _fail(
            "timer_schedule",
            REASON_TIMER_WITHOUT_FUTURE_TRIGGER,
            f"{unit} 在 {scope} scope 下已启用但 NextElapse 为空，不存在未来触发",
            f"检查 OnCalendar 是否被 drop-in 清空，修好后 systemctl --{scope} daemon-reload "
            f"并 restart {unit}。",
        )
    return _ok(
        "timer_schedule",
        f"{unit}（{scope} scope）已启用且有未来触发"
        f"（NextElapseUSecRealtime={properties.get('NextElapseUSecRealtime') or 'n/a'}）",
    )


_CHECKS: Tuple[Callable[["DoctorEnvironment"], DoctorCheck], ...] = (
    _check_entry,
    _check_device_identity,
    _check_timezone,
    _check_runtime_release,
    _check_pythonpath,
    _check_timer,
)


def diagnose(environment: DoctorEnvironment) -> DoctorReport:
    checks = tuple(check(environment) for check in _CHECKS)
    failures = [check for check in checks if check.status == STATUS_FAILED]
    unknowns = [check for check in checks if check.status == STATUS_UNKNOWN]
    # 真实故障优先于「没采到」：不能让一个未知项盖住一个已知坏掉的 timer。
    if failures:
        reason_code = failures[0].reason_code
    elif unknowns:
        reason_code = REASON_PRECHECK_INCOMPLETE
    else:
        reason_code = REASON_OK
    return DoctorReport(
        ok=not failures and not unknowns,
        reason_code=reason_code,
        exit_code=exit_code_for_reason(reason_code),
        checks=checks,
        secret_values=tuple(environment.secret_values or ()),
    )


# --------------------------------------------------------------------------- #
# 只读事实采集
# --------------------------------------------------------------------------- #


ProbeFn = Callable[[str, Mapping[str, str], float], EntryProbe]
CommandRunner = Callable[[Sequence[str]], str]


def derive_probe_url(server_url: str) -> str:
    """把 ingest 地址换成只读健康检查地址，doctor 绝不 POST 业务数据。"""

    parsed = urllib.parse.urlsplit(server_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/health", "", ""))


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止跟随重定向。

    CPython 的默认 `HTTPRedirectHandler` 跟随 3xx 时只会剥掉 Content-Length /
    Content-Type，`Authorization` 原样带到新主机。入口前挂了 captive portal 或
    Cloudflare Access 时，一跳就能把生产 ingest token 交给第三方。
    doctor 是只读预检，没有任何跟随重定向的理由。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def default_probe(url: str, headers: Mapping[str, str], timeout: float) -> EntryProbe:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return EntryProbe(
                url=url,
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        response_headers = {key.lower(): value for key, value in (exc.headers or {}).items()}
        location = response_headers.get("location", "")
        return EntryProbe(
            url=url,
            status=exc.code,
            headers=response_headers,
            body=body,
            redirected=bool(300 <= int(exc.code) < 400 and location),
            redirect_location=location,
        )
    except Exception as exc:  # pragma: no cover - 真实网络故障路径
        return EntryProbe(url=url, error=exc.__class__.__name__)


def default_command_runner(argv: Sequence[str]) -> str:  # pragma: no cover - 真实系统路径
    import subprocess

    completed = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    return completed.stdout or ""


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def collect_environment(
    *,
    config_path: str,
    release_dir: str | None = None,
    timer_unit: str | None = None,
    timer_scope: str = TIMER_SCOPE_USER,
    env: Mapping[str, str] | None = None,
    probe: ProbeFn | None = None,
    command_runner: CommandRunner | None = None,
    timeout: float = 10.0,
    reference_time: str | None = None,
) -> DoctorEnvironment:
    """只读地采集判定所需的事实。这里不写任何文件。"""

    if timer_scope not in TIMER_SCOPES:
        raise ValueError(f"timer_scope must be one of {TIMER_SCOPES}")
    resolved_env = dict(env if env is not None else os.environ)
    probe_fn = probe or default_probe
    runner = command_runner or default_command_runner

    device_config = _read_json(Path(config_path))
    if device_config is None:
        raise DoctorPreconditionError(f"device config unreadable: {config_path}")

    token_env = device_config.get("token_env")
    token_value = resolved_env.get(str(token_env), "") if token_env else ""

    server_url = str(device_config.get("server_url") or "")
    secret_values = _known_secret_values(token_value, server_url)

    probe_url = derive_probe_url(server_url)
    if not probe_url:
        # 没有可用的 server_url 是配置错误，不能报成「网络不可达」去误导用户查网络。
        raise DoctorPreconditionError(
            f"device config server_url is missing or not http(s): {config_path}"
        )
    headers = {"User-Agent": PRODUCT_USER_AGENT, "Accept": "application/json"}
    if token_value:
        headers["Authorization"] = f"Bearer {token_value}"
    entry_probe = probe_fn(probe_url, headers, timeout)

    resolved_release_dir = release_dir or resolved_env.get("AI_USAGE_RELEASE_DIR")
    release_manifest = (
        _read_json(Path(resolved_release_dir) / "release.json") if resolved_release_dir else None
    )

    python_path = [
        entry for entry in (resolved_env.get("PYTHONPATH") or "").split(os.pathsep) if entry
    ]

    timer_properties: Dict[str, str] = {}
    unit_environment: Optional[Dict[str, str]] = None
    unit_package_roots: List[str] = []
    timer_supported = sys.platform.startswith("linux")
    if timer_unit and timer_supported:
        timer_output = _run_systemctl(
            runner,
            [
                "systemctl",
                f"--{timer_scope}",
                "show",
                str(timer_unit),
                "--property=LoadState",
                "--property=UnitFileState",
                "--property=ActiveState",
                "--property=NextElapseUSecRealtime",
                "--property=NextElapseUSecMonotonic",
            ],
        )
        timer_properties = parse_systemctl_show(timer_output) if timer_output is not None else {}

        service_output = _run_systemctl(
            runner,
            [
                "systemctl",
                f"--{timer_scope}",
                "show",
                _service_unit_name(str(timer_unit)),
                "--property=Environment",
            ],
        )
        if service_output is not None:
            properties = parse_systemctl_show(service_output)
            if "Environment" in properties:
                unit_environment = parse_unit_environment(properties["Environment"])
                unit_package_roots = _pythonpath_roots_with_package(
                    unit_environment.get("PYTHONPATH", "")
                )

    return DoctorEnvironment(
        device_config=device_config,
        entry_probe=entry_probe,
        token_env=token_env,
        token_present=bool(token_value),
        system_timezone=_system_timezone(resolved_env),
        observed_identity=_observed_identity(),
        release_dir=resolved_release_dir,
        release_manifest=release_manifest,
        python_path=python_path,
        imported_from=str(Path(__file__).resolve().parent / "__init__.py"),
        unit_environment=unit_environment,
        unit_pythonpath_package_roots=unit_package_roots,
        timer_unit=timer_unit,
        timer_properties=timer_properties,
        timer_scope=timer_scope,
        timer_supported=timer_supported,
        reference_time=reference_time,
        secret_values=secret_values,
    )


def _service_unit_name(timer_unit: str) -> str:
    """同 basename 的 timer/service 由 systemd 自动配对，PYTHONPATH 写在 service 上。"""

    return timer_unit.removesuffix(".timer") + ".service"


def _run_systemctl(runner: CommandRunner, argv: Sequence[str]) -> Optional[str]:
    """执行 systemctl 并容忍它根本不存在。

    拿不到输出返回 None（未知），不是「timer 坏了」，也不能让整个 doctor 崩掉。
    """

    try:
        return runner(list(argv)) or ""
    except OSError:
        return None


def parse_unit_environment(value: str) -> Dict[str, str]:
    """解析 `systemctl show --property=Environment` 的 `K=V K=V` 值。"""

    environment: Dict[str, str] = {}
    try:
        tokens = shlex.split(value or "")
    except ValueError:
        tokens = (value or "").split()
    for token in tokens:
        if "=" not in token:
            continue
        key, _, item = token.partition("=")
        environment[key.strip()] = item
    return environment


def _pythonpath_roots_with_package(pythonpath: str) -> List[str]:
    """PYTHONPATH 里真正含有可导入 ai_usage_widget 的目录（只读探测）。"""

    roots = []
    for entry in str(pythonpath or "").split(os.pathsep):
        if not entry:
            continue
        try:
            if (Path(entry) / "ai_usage_widget" / "__init__.py").exists():
                roots.append(entry)
        except OSError:
            continue
    return roots


def _known_secret_values(token_value: str, server_url: str) -> Tuple[str, ...]:
    """收集本次运行里已知的凭据值，供报告输出前遮蔽。"""

    secrets: List[str] = []
    if token_value:
        secrets.append(token_value)
    try:
        parsed = urllib.parse.urlsplit(server_url)
        for candidate in (parsed.password, parsed.username):
            if candidate:
                secrets.append(candidate)
    except ValueError:
        pass
    return tuple(dict.fromkeys(secrets))


def _system_timezone(env: Mapping[str, str]) -> Optional[str]:
    # POSIX 允许 TZ 带前导冒号（TZ=":Asia/Shanghai"），去掉后才是 IANA 时区名。
    configured = (env.get("TZ") or "").strip().lstrip(":")
    if configured:
        return configured
    try:
        timezone_file = Path("/etc/timezone")
        if timezone_file.exists():
            value = timezone_file.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    try:
        localtime = Path("/etc/localtime")
        if localtime.is_symlink():
            target = os.readlink(localtime)
            marker = "/zoneinfo/"
            if marker in target:
                return target.split(marker, 1)[1]
    except OSError:
        pass
    return None


def _observed_identity() -> Dict[str, str]:
    try:
        os_user = getpass.getuser()
    except Exception:  # pragma: no cover - 无 passwd 条目的极端环境
        os_user = ""
    if sys.platform == "darwin":
        platform = "darwin"
    elif sys.platform.startswith("win"):
        platform = "windows"
    else:
        platform = "linux"
    return {
        "machine": socket.gethostname(),
        "os_user": os_user,
        "platform": platform,
    }


def run_deploy_doctor(
    *,
    config_path: str | None = None,
    environment_fixture: str | None = None,
    release_dir: str | None = None,
    timer_unit: str | None = None,
    timer_scope: str = TIMER_SCOPE_USER,
    env: Mapping[str, str] | None = None,
    probe: ProbeFn | None = None,
    command_runner: CommandRunner | None = None,
    timeout: float = 10.0,
) -> DoctorReport:
    if environment_fixture:
        fixture = _read_json(Path(environment_fixture))
        if fixture is None:
            raise DoctorPreconditionError(f"doctor environment fixture unreadable: {environment_fixture}")
        return diagnose(DoctorEnvironment.from_fixture(fixture))
    if not config_path:
        raise DoctorPreconditionError("doctor requires --config or --environment-fixture")
    environment = collect_environment(
        config_path=config_path,
        release_dir=release_dir,
        timer_unit=timer_unit,
        timer_scope=timer_scope,
        env=env,
        probe=probe,
        command_runner=command_runner,
        timeout=timeout,
    )
    return diagnose(environment)


__all__ = [
    "CATEGORY_EXIT_CODES",
    "DIAGNOSTIC_REASON_CODES",
    "DoctorCheck",
    "DoctorEnvironment",
    "DoctorReport",
    "EXIT_DOCTOR_ERROR",
    "DoctorPreconditionError",
    "EntryProbe",
    "ADDITIONAL_REASON_CODES",
    "ALL_REASON_CODES",
    "REASON_CATEGORIES",
    "REASON_OK",
    "REASON_PRECHECK_INCOMPLETE",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "STATUS_UNKNOWN",
    "SECRET_MASK",
    "TIMER_SCOPES",
    "TIMER_SCOPE_SYSTEM",
    "TIMER_SCOPE_USER",
    "category_for_reason",
    "collect_environment",
    "derive_probe_url",
    "diagnose",
    "exit_code_for_reason",
    "has_future_trigger",
    "is_unit_enabled",
    "looks_like_health_payload",
    "mask_secrets",
    "parse_systemctl_show",
    "parse_unit_environment",
    "redact_url",
    "run_deploy_doctor",
]
