"""verify-cloud：云端读模型的**只读**核对入口（Issue #60）。

给没有图形界面的环境（Linux CLI）一个可判定的核对手段：同一份事实，读模型给的是什么，
就原样打出来，并按产品不变量判定「可信」还是「降级」。

硬边界（由 `tests/test_architecture_governance.py::TestVerifyCloudReadOnlyBoundary` 固化，
不是口头约定）：

- **只读**：本模块只发只读请求（GET），源码里不出现任何写方法字面量或写接口路径。
- **不重算口径**：只消费 `/api/summary`、`/api/mobile/summary`、`/api/health` 的成品字段，
  不求和、不算百分比、不重新聚合。造出第三套数字比没有工具更糟。
- **不泄露**：凭据只从环境变量读，只出现在请求头里；输出不含凭据、auth 路径或原始用量日志。

退出码有语义，见本模块的 `EXIT_*` 常量。
"""

from __future__ import annotations

import http.client as httpclient
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib import error as urlerror, parse as urlparse, request as urlrequest

from .http_identity import PRODUCT_USER_AGENT


# --- 退出码 -----------------------------------------------------------------

#: 核对通过。
EXIT_OK = 0
#: 读模型自己标记了降级态 / 结构异常（额度不可信、来源掉线、归属不完整…）。
EXIT_DATA_ISSUE = 3
#: `/api/summary` 与 `/api/mobile/summary` 对同一周期口径不一致。
EXIT_PARITY_MISMATCH = 4
#: 取数失败（缺凭据、网络错误、fixture 缺失、响应不是 JSON）。
#: 与「数据有问题」分开，否则拿不到数和数不对会被混成同一个结论。
EXIT_FETCH_FAILED = 5


# --- 只读端点 ---------------------------------------------------------------

ENDPOINT_SUMMARY = "summary"
ENDPOINT_MOBILE_SUMMARY = "mobile_summary"
ENDPOINT_HEALTH = "health"

#: 本模块允许触达的全部端点。都是只读的 `/api/*` 查询接口。
READ_ONLY_PATHS = {
    ENDPOINT_SUMMARY: "/api/summary",
    ENDPOINT_MOBILE_SUMMARY: "/api/mobile/summary",
    ENDPOINT_HEALTH: "/api/health",
}

FIXTURE_FILENAMES = {
    ENDPOINT_SUMMARY: "summary.json",
    ENDPOINT_MOBILE_SUMMARY: "mobile_summary.json",
    ENDPOINT_HEALTH: "health.json",
}

#: 固定 provider 槽位，顺序恒定。口径 owner 是 `snapshot_builder`，这里只核对顺序没变。
SLOT_PROVIDERS = ("claude", "codex")

DEFAULT_TOKEN_ENV = "AI_USAGE_READ_TOKEN"

_MISSING_TEXT = "—"


class ReadSourceError(Exception):
    """取数失败。消息里只允许出现端点名、环境变量名和错误原因，绝不含凭据值。"""


class FixtureReadSource:
    """离线重放：从目录里读已经落盘的读模型响应。无网络、无凭据。"""

    def __init__(self, directory: str) -> None:
        self._directory = Path(directory)

    @property
    def label(self) -> str:
        return "fixture"

    def read(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        del params  # 离线重放按端点整份回放，不做服务端过滤
        # 刻意用 joinpath 而不是 `/`：本模块的只读边界检查禁止一切算术运算符，
        # 为「这个除号其实是路径拼接」开例外，等于给真正的重算留了后门。
        path = self._directory.joinpath(FIXTURE_FILENAMES[endpoint])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReadSourceError(f"fixture 缺少端点 {endpoint} 的响应文件: {path.name}") from exc
        return _decode_json(text, endpoint)


class HttpReadSource:
    """在线只读：对 `/api/*` 发只读请求，凭据只进请求头。"""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        # URL 里带 userinfo 时，CPython 到 urlopen 阶段才抛 InvalidURL，而异常信息里
        # 含密码原文；它继承自 HTTPException 而非 HTTPError/URLError，read() 捕不到，
        # 密码会随 traceback 打到 stderr。只读凭据只走请求头，URL 里本就不该有
        # userinfo，直接在入口拒绝，且不回显它。
        if "@" in urlparse.urlsplit(base_url).netloc:
            raise ReadSourceError("基地址不得包含 userinfo：只读凭据只能通过环境变量传入")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @property
    def label(self) -> str:
        """只暴露 scheme 与主机名：URL 的 path/query 可能被使用者塞进敏感串。"""
        parsed = urlparse.urlsplit(self._base_url)
        if not parsed.scheme or not parsed.netloc:
            return "http"
        return f"{parsed.scheme}://{parsed.hostname or ''}"

    def build_request(self, endpoint: str, params: Dict[str, Any]) -> urlrequest.Request:
        query = urlparse.urlencode(
            {key: value for key, value in sorted(params.items()) if value is not None}
        )
        path = READ_ONLY_PATHS[endpoint]
        url = f"{self._base_url}{path}?{query}" if query else f"{self._base_url}{path}"
        try:
            return urlrequest.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                    "User-Agent": PRODUCT_USER_AGENT,
                },
                method="GET",
            )
        except ValueError as exc:
            # 只报「基地址不可用」，不回显 URL：使用者可能把凭据塞进了 query。
            raise ReadSourceError(f"基地址不可用，无法构造只读请求：{endpoint}") from exc

    def read(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        req = self.build_request(endpoint, params)
        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as response:
                text = response.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            raise ReadSourceError(f"读取 {endpoint} 失败：HTTP {exc.code}") from exc
        except urlerror.URLError as exc:
            raise ReadSourceError(f"读取 {endpoint} 失败：{exc.reason}") from exc
        except UnicodeDecodeError as exc:
            # 响应体不是 UTF-8。原始字节可能是任何东西，不回显。
            raise ReadSourceError(f"读取 {endpoint} 失败：响应体不是合法 UTF-8") from exc
        except (OSError, httpclient.HTTPException) as exc:
            # body 读取阶段的超时/连接中断落在 urlopen 自身的保护范围之外；
            # InvalidURL 之类要到 urlopen 才暴露，且继承自 HTTPException 而非 OSError，
            # 两个基类都要兜。只报异常类名——异常信息里可能夹带 URL 片段。
            raise ReadSourceError(f"读取 {endpoint} 失败：{exc.__class__.__name__}") from exc
        return _decode_json(text, endpoint)


def _decode_json(text: str, endpoint: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReadSourceError(f"端点 {endpoint} 的响应不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise ReadSourceError(f"端点 {endpoint} 的响应必须是 JSON 对象")
    return parsed


def build_read_source(args) -> "FixtureReadSource | HttpReadSource":
    if args.fixture_dir and args.base_url:
        raise ReadSourceError("--fixture-dir 与 --base-url 只能二选一")
    if args.fixture_dir:
        return FixtureReadSource(args.fixture_dir)
    if not args.base_url:
        raise ReadSourceError("需要 --base-url（在线只读）或 --fixture-dir（离线重放）")
    token = os.environ.get(args.token_env, "")
    if not token.strip():
        raise ReadSourceError(f"缺少只读凭据环境变量: {args.token_env}")
    return HttpReadSource(args.base_url, token, timeout=args.timeout)


def read_params(args) -> Dict[str, Any]:
    return {
        "date": args.date,
        "period": args.period,
        "machine": args.machine,
        "account": args.account,
    }


# --- summary 核对 -----------------------------------------------------------


def build_summary_report(
    document: Dict[str, Any],
    *,
    requested: Dict[str, Any],
    source_label: str,
) -> Dict[str, Any]:
    """把 `/api/summary` 的成品字段整理成核对报告。全部字段直取，不重算。"""
    issues: List[Dict[str, str]] = []
    summary = document.get("summary")
    if not isinstance(summary, dict):
        issues.append(_issue("summary_block_missing", "响应里没有 summary 块，无法核对周期用量"))
        summary = {}

    period = {
        "id": summary.get("period"),
        "date": summary.get("date"),
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "machine": summary.get("machine"),
        "account": summary.get("account"),
    }
    totals = {
        field: summary.get(field)
        for field in (
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
        )
    }

    _check_requested_filters(requested, period, issues)

    slots, coverage = _slots_and_coverage(document, issues)

    return _finish_report(
        {
            "command": "summary",
            "source": source_label,
            "generated_at": document.get("generated_at"),
            "timezone": document.get("timezone"),
            "requested": dict(requested),
            "period": period,
            "totals": totals,
            "provider_slots": slots,
            "coverage": coverage,
        },
        issues,
        EXIT_DATA_ISSUE,
        "data_issue",
    )


def _slots_and_coverage(document: Dict[str, Any], issues: List[Dict[str, str]]):
    raw_slots = document.get("provider_slots")
    slots: List[Dict[str, Any]] = []
    if not isinstance(raw_slots, list):
        issues.append(_issue("provider_slots_missing", "响应里没有 provider_slots，无法按 provider 核对"))
    else:
        slots = [_slot_row(row) for row in raw_slots if isinstance(row, dict)]
        if tuple(row["provider"] for row in slots) != SLOT_PROVIDERS:
            issues.append(_issue(
                "provider_slots_unexpected",
                f"provider 槽位应恒为 {list(SLOT_PROVIDERS)}，实际是 {[row['provider'] for row in slots]}",
            ))

    raw_coverage = document.get("provider_usage_coverage")
    coverage: Dict[str, Any] = {}
    if not isinstance(raw_coverage, dict):
        issues.append(_issue(
            "provider_usage_coverage_missing",
            "响应里没有 provider_usage_coverage，无法判断周期总量是否全部有归属",
        ))
    else:
        coverage = {
            field: raw_coverage.get(field)
            for field in (
                "status",
                "total_tokens",
                "attributed_tokens",
                "other_provider_tokens",
                "unattributed_tokens",
            )
        }
        if coverage["status"] != "complete":
            issues.append(_issue(
                "usage_attribution_partial",
                "周期总量没有全部归入固定槽位："
                f"其它 provider {_show(coverage['other_provider_tokens'])}，"
                f"无法归属 {_show(coverage['unattributed_tokens'])}",
            ))
    return slots, coverage


def _slot_row(row: Dict[str, Any]) -> Dict[str, Any]:
    usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
    quota = row.get("quota") if isinstance(row.get("quota"), dict) else {}
    windows = quota.get("windows") if isinstance(quota.get("windows"), list) else []
    return {
        "provider": row.get("provider"),
        "usage_status": usage.get("status"),
        "total_tokens": usage.get("total_tokens"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_tokens": usage.get("cache_tokens"),
        "quota_status": quota.get("status"),
        "quota_reason": quota.get("reason"),
        "quota_last_verified_at": quota.get("last_verified_at"),
        "quota_source_id": quota.get("source_id"),
        "quota_source_type": quota.get("source_type"),
        "quota_window_count": len(windows),
    }


def _check_requested_filters(
    requested: Dict[str, Any],
    period: Dict[str, Any],
    issues: List[Dict[str, str]],
) -> None:
    """显式请求过的过滤条件必须被读模型采纳，否则核对的根本不是同一份切片。"""
    pairs = (
        ("period", "id", "period_mismatch"),
        ("date", "date", "date_mismatch"),
        ("machine", "machine", "machine_mismatch"),
        ("account", "account", "account_mismatch"),
    )
    for request_key, period_key, code in pairs:
        wanted = requested.get(request_key)
        if wanted is None:
            continue
        actual = period.get(period_key)
        if actual != wanted:
            issues.append(_issue(
                code,
                f"请求 {request_key}={wanted}，读模型返回的是 {_show(actual)}",
            ))


def render_summary(report: Dict[str, Any]) -> str:
    lines = [
        "verify-cloud summary",
        _rule(),
        f"数据源          : {report['source']}",
        f"读模型生成时间  : {_show(report['generated_at'])}",
        f"时区            : {_show(report['timezone'])}",
        f"周期            : {_show(report['period']['id'])}"
        f"  {_show(report['period']['start_date'])} ~ {_show(report['period']['end_date'])}",
        f"快照日期        : {_show(report['period']['date'])}",
        f"机器过滤        : {_show(report['period']['machine'])}",
        f"账户过滤        : {_show(report['period']['account'])}",
        "",
        "周期用量（读模型口径，未在 CLI 侧重算）",
        f"  总 token        : {_show(report['totals']['total_tokens'])}",
        f"  输入 token      : {_show(report['totals']['input_tokens'])}",
        f"  输出 token      : {_show(report['totals']['output_tokens'])}",
        f"  缓存写入 token  : {_show(report['totals']['cache_creation_tokens'])}",
        f"  缓存读取 token  : {_show(report['totals']['cache_read_tokens'])}",
        "",
        "provider 槽位",
        f"  {'provider':<10}{'用量状态':<12}{'总 token':>14}{'输入':>12}{'输出':>12}{'缓存':>12}  额度状态",
    ]
    for row in report["provider_slots"]:
        quota_reason = row["quota_reason"]
        quota_text = _show(row["quota_status"]) if quota_reason is None else f"{_show(row['quota_status'])} ({quota_reason})"
        lines.append(
            f"  {_show(row['provider']):<10}{_show(row['usage_status']):<12}"
            f"{_show(row['total_tokens']):>14}{_show(row['input_tokens']):>12}"
            f"{_show(row['output_tokens']):>12}{_show(row['cache_tokens']):>12}"
            f"  {quota_text}"
        )
    coverage = report["coverage"]
    lines.extend([
        "",
        "用量归属覆盖",
        f"  状态            : {_show(coverage.get('status'))}",
        f"  周期总量        : {_show(coverage.get('total_tokens'))}",
        f"  已归入槽位      : {_show(coverage.get('attributed_tokens'))}",
        f"  其它 provider   : {_show(coverage.get('other_provider_tokens'))}",
        f"  无法归属        : {_show(coverage.get('unattributed_tokens'))}",
    ])
    lines.extend(_render_issues(report))
    return "\n".join(lines)


# --- limits 核对 ------------------------------------------------------------

#: 只有三项同时成立才算可信官方额度（AGENTS.md 不变量，本模块只判定不重算）。
TRUST_OFFICIAL = "trusted_official"
TRUST_DEGRADED = "degraded"

TRUST_LABELS = {
    TRUST_OFFICIAL: "可信官方额度",
    TRUST_DEGRADED: "降级",
}


def build_limits_report(
    document: Dict[str, Any],
    *,
    requested: Dict[str, Any],
    source_label: str,
) -> Dict[str, Any]:
    """逐条标注额度窗口的 official / confidence / status，并判定可信还是降级。"""
    issues: List[Dict[str, str]] = []
    raw_windows = document.get("limits")
    windows: List[Dict[str, Any]] = []
    if not isinstance(raw_windows, list):
        issues.append(_issue("limit_windows_missing", "响应里没有 limits 列表，无法核对额度窗口"))
    else:
        windows = [_limit_row(row) for row in raw_windows if isinstance(row, dict)]
        if not windows:
            issues.append(_issue("limit_windows_missing", "读模型没有返回任何额度窗口，当前没有可核对的官方额度"))

    trusted = [row for row in windows if row["trust"] == TRUST_OFFICIAL]
    degraded = [row for row in windows if row["trust"] == TRUST_DEGRADED]
    for row in degraded:
        issues.append(_issue(
            "limit_window_degraded",
            f"{_show(row['provider'])}/{_show(row['window'])} 不能当官方额度展示："
            f"{', '.join(row['degrade_reasons'])}",
        ))

    provider_quota = _provider_quota_rows(document)
    for row in provider_quota:
        if row["status"] != "available":
            issues.append(_issue(
                "provider_quota_unavailable",
                f"{_show(row['provider'])} 当前没有可信官方额度：{_show(row['reason'])}",
            ))

    return _finish_report(
        {
            "command": "limits",
            "source": source_label,
            "generated_at": document.get("generated_at"),
            "timezone": document.get("timezone"),
            "requested": dict(requested),
            "trusted_count": len(trusted),
            "degraded_count": len(degraded),
            "provider_quota": provider_quota,
            "windows": windows,
        },
        issues,
        EXIT_DATA_ISSUE,
        "data_issue",
    )


def _limit_row(row: Dict[str, Any]) -> Dict[str, Any]:
    official = row.get("official")
    confidence = row.get("confidence")
    status = row.get("status")
    reasons: List[str] = []
    if official is not True:
        reasons.append("not_official")
    if confidence != "observed":
        reasons.append(f"confidence_{_show(confidence)}")
    if status != "ok":
        reasons.append(f"status_{_show(status)}")
    trusted = not reasons
    return {
        "provider": row.get("provider"),
        "window": row.get("window"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "official": official,
        "confidence": confidence,
        "status": status,
        "trust": TRUST_OFFICIAL if trusted else TRUST_DEGRADED,
        "degrade_reasons": reasons,
        # 降级窗口一律不带百分比和 reset 时间：这些数字只有在官方额度可信时才有意义，
        # 原样透出等于让本地估算冒充官方额度。
        "used_percent": row.get("used_percent") if trusted else None,
        "remaining_percent": row.get("remaining_percent") if trusted else None,
        "reset_at": row.get("reset_at") if trusted else None,
        "window_duration_minutes": row.get("window_duration_minutes") if trusted else None,
        "observed_at": row.get("observed_at"),
    }


def _provider_quota_rows(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_slots = document.get("provider_slots")
    if not isinstance(raw_slots, list):
        return []
    rows = []
    for slot in raw_slots:
        if not isinstance(slot, dict):
            continue
        quota = slot.get("quota") if isinstance(slot.get("quota"), dict) else {}
        windows = quota.get("windows") if isinstance(quota.get("windows"), list) else []
        rows.append({
            "provider": slot.get("provider"),
            "status": quota.get("status"),
            "reason": quota.get("reason"),
            "last_verified_at": quota.get("last_verified_at"),
            "source_id": quota.get("source_id"),
            "source_type": quota.get("source_type"),
            "window_count": len(windows),
        })
    return rows


def render_limits(report: Dict[str, Any]) -> str:
    lines = [
        "verify-cloud limits",
        _rule(),
        f"数据源          : {report['source']}",
        f"读模型生成时间  : {_show(report['generated_at'])}",
        # 计数行刻意不复用「可信官方额度」「降级」这两个判定词：
        # 判定词只出现在窗口逐条判定里，扫一眼就知道哪几条不能信。
        f"可信窗口数      : {report['trusted_count']}",
        f"不可信窗口数    : {report['degraded_count']}",
        "",
        "provider 额度可用性",
        f"  {'provider':<10}{'状态':<12}{'原因':<16}{'最近一次官方核对':<28}来源",
    ]
    for row in report["provider_quota"]:
        lines.append(
            f"  {_show(row['provider']):<10}{_show(row['status']):<12}{_show(row['reason']):<16}"
            f"{_show(row['last_verified_at']):<28}{_show(row['source_type'])}"
        )
    lines.extend([
        "",
        "额度窗口（逐条标注 official / confidence / status）",
        f"  {'判定':<14}{'provider':<10}{'window':<12}{'official':<10}{'confidence':<12}"
        f"{'status':<16}{'已用%':>8}{'剩余%':>8}  {'重置时间':<28}{'观测时间':<28}来源类型",
    ])
    for row in report["windows"]:
        lines.append(
            f"  {TRUST_LABELS[row['trust']]:<14}{_show(row['provider']):<10}{_show(row['window']):<12}"
            f"{_show(row['official']):<10}{_show(row['confidence']):<12}{_show(row['status']):<16}"
            f"{_show(row['used_percent']):>8}{_show(row['remaining_percent']):>8}  "
            f"{_show(row['reset_at']):<28}{_show(row['observed_at']):<28}{_show(row['source_type'])}"
        )
    lines.extend(_render_issues(report))
    return "\n".join(lines)


# --- health 核对 ------------------------------------------------------------


def build_health_report(
    summary_document: Dict[str, Any],
    health_document: Dict[str, Any],
    *,
    requested: Dict[str, Any],
    source_label: str,
) -> Dict[str, Any]:
    """各来源最后上报时间、新鲜度、覆盖范围与准确性状态。

    `/api/health` 里的 `database.path` / `snapshot.path` 是服务端本机路径，
    刻意不进报告：核对工具没有理由把服务器文件布局打印到终端或 CI 日志里。
    """
    issues: List[Dict[str, str]] = []
    raw_status = summary_document.get("source_status")
    sources: List[Dict[str, Any]] = []
    if not isinstance(raw_status, list):
        issues.append(_issue("source_status_missing", "响应里没有 source_status，无法核对来源健康"))
    else:
        sources = [_health_source_row(row) for row in raw_status if isinstance(row, dict)]

    for row in sources:
        if row["status"] != "ok":
            issues.append(_issue(
                "source_not_ok",
                f"{_show(row['display_name'])}（{_show(row['source_id'])}）状态为 {_show(row['status'])}，"
                f"最后上报 {_show(row['last_observed_at'])}",
            ))
        if row["version_state"] == "unsupported":
            issues.append(_issue(
                "collector_version_unsupported",
                f"{_show(row['display_name'])} 的采集端版本 {_show(row['collector_version'])} 已不受支持",
            ))

    health_sources = health_document.get("source_status")
    health_sources = health_sources if isinstance(health_sources, dict) else {}
    source_total = health_sources.get("total")
    # `/api/health` 不吃 machine / account 过滤，带过滤时两端数量本来就该不同，不做交叉核对。
    filtered = requested.get("machine") is not None or requested.get("account") is not None
    if not filtered and isinstance(raw_status, list) and source_total != len(sources):
        issues.append(_issue(
            "source_count_mismatch",
            f"/api/health 报告 {_show(source_total)} 个来源，/api/summary 只有 {len(sources)} 个",
        ))

    # 后端没有版本读取侧时（生产 Worker 今天就是这样，见 Issue #63），版本维度
    # 根本没被核对过。这时候判「核对通过」等于把那个缺口翻译成绿灯：使用者会以为
    # 「哪台设备还在跑旧采集器」已经查过了。**未核对不等于核对通过**，必须说出来。
    versions_raw = health_document.get("versions")
    if not isinstance(versions_raw, dict):
        issues.append(_issue(
            "version_block_unavailable",
            "/api/health 没有 versions 块：本后端未实现版本读取侧，版本维度未核对",
        ))
    if sources and all(row["version_state"] is None for row in sources):
        issues.append(_issue(
            "version_block_unavailable",
            "/api/summary 的 source_status 没有 version 块：本后端未实现版本读取侧，"
            "无法判断哪些采集端落后或不兼容",
        ))

    versions = versions_raw if isinstance(versions_raw, dict) else {}
    snapshot = health_document.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    limits_health = health_document.get("limits")
    limits_health = limits_health if isinstance(limits_health, dict) else {}

    return _finish_report(
        {
            "command": "health",
            "source": source_label,
            "generated_at": health_document.get("generated_at"),
            "backend_mode": health_document.get("backend_mode"),
            "canonical_store": health_document.get("canonical_store"),
            "snapshot_updated_at": snapshot.get("updated_at"),
            "requested": dict(requested),
            "source_total": source_total,
            "status_counts": health_sources.get("counts"),
            "version_counts": versions.get("counts"),
            "limits_health": {
                field: limits_health.get(field)
                for field in (
                    "latest_observed_at",
                    "effective_window_count",
                    "raw_window_count",
                    "stale_window_count",
                )
            },
            "sources": sources,
        },
        issues,
        EXIT_DATA_ISSUE,
        "data_issue",
    )


def _health_source_row(row: Dict[str, Any]) -> Dict[str, Any]:
    accuracy = row.get("accuracy") if isinstance(row.get("accuracy"), dict) else {}
    version = row.get("version") if isinstance(row.get("version"), dict) else {}
    agents = accuracy.get("agents") if isinstance(accuracy.get("agents"), list) else []
    return {
        "source_id": row.get("source_id"),
        "display_name": row.get("display_name"),
        "machine": row.get("machine"),
        "os_user": row.get("os_user"),
        "platform": row.get("platform"),
        "status": row.get("status"),
        "last_observed_at": row.get("observed_at"),
        "accuracy_status": accuracy.get("status"),
        "version_state": version.get("state"),
        "collector_version": version.get("collector_version"),
        "coverage": [_coverage_row(agent) for agent in agents if isinstance(agent, dict)],
    }


def _coverage_row(agent: Dict[str, Any]) -> Dict[str, Any]:
    coverage = agent.get("coverage") if isinstance(agent.get("coverage"), dict) else {}
    return {
        "agent": agent.get("agent"),
        "status": agent.get("status"),
        "start": coverage.get("start"),
        "end": coverage.get("end"),
    }


def render_health(report: Dict[str, Any]) -> str:
    lines = [
        "verify-cloud health",
        _rule(),
        f"数据源          : {report['source']}",
        f"健康检查时间    : {_show(report['generated_at'])}",
        f"快照更新时间    : {_show(report['snapshot_updated_at'])}",
        f"后端模式        : {_show(report['backend_mode'])} / {_show(report['canonical_store'])}",
        f"来源总数        : {_show(report['source_total'])}",
        f"状态分布        : {_show_counts(report['status_counts'])}",
        f"版本状态分布    : {_show_counts(report['version_counts'])}",
        "",
        "官方额度新鲜度",
        f"  最近一次官方核对: {_show(report['limits_health']['latest_observed_at'])}",
        f"  有效窗口 / 全部 : {_show(report['limits_health']['effective_window_count'])}"
        f" / {_show(report['limits_health']['raw_window_count'])}",
        f"  陈旧窗口        : {_show(report['limits_health']['stale_window_count'])}",
        "",
        "各来源",
        f"  {'source_id':<24}{'新鲜度':<14}{'最后上报':<28}{'准确性':<12}{'版本':<20}覆盖范围",
    ]
    for row in report["sources"]:
        coverage = "; ".join(
            f"{_show(item['agent'])} {_show(item['start'])}~{_show(item['end'])}"
            for item in row["coverage"]
        )
        lines.append(
            f"  {_show(row['source_id']):<24}{_show(row['status']):<14}"
            f"{_show(row['last_observed_at']):<28}{_show(row['accuracy_status']):<12}"
            f"{_show(row['version_state']):<20}{coverage if coverage else _MISSING_TEXT}"
        )
    lines.extend(_render_issues(report))
    return "\n".join(lines)


# --- parity 核对 ------------------------------------------------------------

#: `/api/mobile/summary` 与 `/api/summary` 之间**有意**的差异。
#: 它们不是口径不一致，绝不能被 parity 报成差异，否则真实差异会被噪声淹没。
KNOWN_MOBILE_OMISSIONS = (
    {
        "field": "source_status[].version",
        "reason": "Mobile DTO 不消费采集端版本字段，缺失是设计如此",
    },
    {
        "field": "version_health",
        "reason": "版本健康只出现在 /api/summary 与 /api/health，Mobile DTO 不消费",
    },
    {
        "field": "summary.cache_creation_tokens / summary.cache_read_tokens",
        "reason": "Mobile DTO 只保留合并后的 cache_tokens，两边不是同一个字段，不做逐字段比对",
    },
)


def build_parity_report(
    summary_document: Dict[str, Any],
    mobile_document: Dict[str, Any],
    *,
    requested: Dict[str, Any],
    source_label: str,
) -> Dict[str, Any]:
    """比对两个端点对同一周期的口径。只比对**两边都有**的同名事实。"""
    summary_facts = _parity_facts(
        _summary_period(summary_document),
        summary_document.get("provider_slots"),
        summary_document.get("provider_usage_coverage"),
    )
    mobile_facts = _parity_facts(
        mobile_document.get("period"),
        mobile_document.get("provider_slots"),
        mobile_document.get("provider_usage_coverage"),
    )

    fields = sorted(summary_facts)

    # 结构下限。两个端点由同一个服务端提供，会共享失败模式（200 + 错误信封、CDN 缓存
    # 了空对象、read model 抛错后返回兜底空快照）。两边同时退化成同形状的垃圾时，逐字段
    # 比对拿到的全是 None，None == None，差异为空，parity 会报「核对通过」。这是最难被
    # 发现的假绿：它长得像核对结果，而 README 把这个退出码写成可以直接进 CI 的门禁。
    unusable = [
        f"/api/{name}"
        for name, facts in (("summary", summary_facts), ("mobile/summary", mobile_facts))
        if facts.get("period.id") is None or facts.get("period.total_tokens") is None
    ]
    if unusable:
        return _finish_report(
            {
                "command": "parity",
                "source": source_label,
                "requested": dict(requested),
                "summary_generated_at": summary_document.get("generated_at"),
                "mobile_generated_at": mobile_document.get("generated_at"),
                "compared_fields": fields,
                "differences": [],
                "known_differences": [dict(row) for row in KNOWN_MOBILE_OMISSIONS],
            },
            [
                _issue(
                    "parity_input_unusable",
                    f"{endpoint} 没有可比对的周期与总量，无法据此判定口径一致",
                )
                for endpoint in unusable
            ],
            EXIT_DATA_ISSUE,
            "data_issue",
        )

    differences = [
        {"field": field, "summary": summary_facts[field], "mobile": mobile_facts[field]}
        for field in fields
        if summary_facts[field] != mobile_facts[field]
    ]
    issues = [
        _issue(
            "parity_mismatch",
            f"{row['field']}：/api/summary={_show(row['summary'])}，"
            f"/api/mobile/summary={_show(row['mobile'])}",
        )
        for row in differences
    ]

    report = _finish_report(
        {
            "command": "parity",
            "source": source_label,
            "requested": dict(requested),
            "summary_generated_at": summary_document.get("generated_at"),
            "mobile_generated_at": mobile_document.get("generated_at"),
            "compared_fields": fields,
            "differences": differences,
            "known_differences": [dict(row) for row in KNOWN_MOBILE_OMISSIONS],
        },
        issues,
        EXIT_PARITY_MISMATCH,
        "mismatch",
    )
    return report


def _summary_period(document: Dict[str, Any]) -> Dict[str, Any]:
    """把 `/api/summary` 的 summary 块改写成与 Mobile DTO `period` 同名的形状。

    只是换个 key 名对齐（`period` -> `id`），值一律直取，不做任何换算。
    """
    raw = document.get("summary") if isinstance(document.get("summary"), dict) else {}
    return {
        "id": raw.get("period"),
        "date": raw.get("date"),
        "start_date": raw.get("start_date"),
        "end_date": raw.get("end_date"),
        "machine": raw.get("machine"),
        "account": raw.get("account"),
        "total_tokens": raw.get("total_tokens"),
        "input_tokens": raw.get("input_tokens"),
        "output_tokens": raw.get("output_tokens"),
    }


def _parity_facts(period: Any, slots: Any, coverage: Any) -> Dict[str, Any]:
    period = period if isinstance(period, dict) else {}
    coverage = coverage if isinstance(coverage, dict) else {}
    slot_rows = slots if isinstance(slots, list) else []
    by_provider = {
        row.get("provider"): row
        for row in slot_rows
        if isinstance(row, dict)
    }

    facts: Dict[str, Any] = {
        f"period.{field}": period.get(field)
        for field in (
            "id",
            "date",
            "start_date",
            "end_date",
            "machine",
            "account",
            "total_tokens",
            "input_tokens",
            "output_tokens",
        )
    }
    for provider in SLOT_PROVIDERS:
        slot = by_provider.get(provider)
        slot = slot if isinstance(slot, dict) else {}
        usage = slot.get("usage") if isinstance(slot.get("usage"), dict) else {}
        quota = slot.get("quota") if isinstance(slot.get("quota"), dict) else {}
        windows = quota.get("windows") if isinstance(quota.get("windows"), list) else []
        prefix = f"provider_slots[{provider}]"
        for field in ("status", "total_tokens", "input_tokens", "output_tokens", "cache_tokens"):
            facts[f"{prefix}.usage.{field}"] = usage.get(field)
        for field in ("status", "reason", "last_verified_at", "source_id", "source_type"):
            facts[f"{prefix}.quota.{field}"] = quota.get(field)
        facts[f"{prefix}.quota.window_count"] = len(windows)
    for field in (
        "status",
        "total_tokens",
        "attributed_tokens",
        "other_provider_tokens",
        "unattributed_tokens",
    ):
        facts[f"provider_usage_coverage.{field}"] = coverage.get(field)
    return facts


def render_parity(report: Dict[str, Any]) -> str:
    lines = [
        "verify-cloud parity",
        _rule(),
        f"数据源              : {report['source']}",
        f"/api/summary 生成时间       : {_show(report['summary_generated_at'])}",
        f"/api/mobile/summary 生成时间: {_show(report['mobile_generated_at'])}",
        f"比对字段数          : {len(report['compared_fields'])}",
        f"不一致字段数        : {len(report['differences'])}",
        "",
        "已知的有意差异（不参与比对）",
    ]
    for row in report["known_differences"]:
        lines.append(f"  {row['field']}：{row['reason']}")
    if report["differences"]:
        lines.extend([
            "",
            "逐字段差异",
            f"  {'字段':<48}{'/api/summary':<28}/api/mobile/summary",
        ])
        for row in report["differences"]:
            lines.append(
                f"  {row['field']:<48}{_show(row['summary']):<28}{_show(row['mobile'])}"
            )
    lines.extend(_render_issues(report))
    return "\n".join(lines)


# --- 通用工具 ---------------------------------------------------------------


def _finish_report(
    report: Dict[str, Any],
    issues: List[Dict[str, str]],
    failure_code: int,
    failure_status: str,
) -> Dict[str, Any]:
    report["issues"] = issues
    report["status"] = failure_status if issues else "ok"
    report["exit_code"] = failure_code if issues else EXIT_OK
    return report


def _issue(code: str, detail: str) -> Dict[str, str]:
    return {"code": code, "detail": detail}


def _render_issues(report: Dict[str, Any]) -> List[str]:
    if not report["issues"]:
        return ["", _rule(), f"结论：核对通过（退出码 {report['exit_code']}）"]
    lines = ["", _rule(), "发现问题："]
    for issue in report["issues"]:
        lines.append(f"  [{issue['code']}] {issue['detail']}")
    lines.append(f"结论：核对未通过（退出码 {report['exit_code']}）")
    return lines


def _rule() -> str:
    return "".ljust(72, "-")


def _show_counts(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return _MISSING_TEXT
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _show(value: Any) -> str:
    if value is None:
        return _MISSING_TEXT
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


# --- CLI 接线 ---------------------------------------------------------------


def register_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "verify-cloud",
        help="只读核对云端读模型（不写任何数据）",
    )
    commands = parser.add_subparsers(dest="verify_command", required=True)
    for name, description in (
        ("summary", "打印周期用量关键口径"),
        ("limits", "打印当前额度窗口，逐条标注 official / confidence / status"),
        ("health", "打印各来源最后上报时间、新鲜度、覆盖范围与准确性状态"),
        ("parity", "比对 /api/summary 与 /api/mobile/summary 对同一周期的口径"),
    ):
        sub = commands.add_parser(name, help=description)
        _add_common_arguments(sub)


def _add_common_arguments(parser) -> None:
    parser.add_argument("--base-url", default=None, help="在线只读：服务端基地址")
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="承载只读凭据的环境变量名（只读取，不打印）",
    )
    parser.add_argument("--fixture-dir", default=None, help="离线重放：已落盘的读模型响应目录")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--date", default=None, help="快照日期 YYYY-MM-DD")
    parser.add_argument("--period", default=None, choices=["today", "week", "month", "all"])
    parser.add_argument("--machine", default=None)
    parser.add_argument("--account", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出机器可判定结构")


def run(args) -> int:
    try:
        source = build_read_source(args)
    except ReadSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FETCH_FAILED

    params = read_params(args)
    try:
        report = _dispatch(args, source, params)
    except ReadSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FETCH_FAILED

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(_render(report))
    return report["exit_code"]


def _dispatch(args, source, params: Dict[str, Any]) -> Dict[str, Any]:
    if args.verify_command == "summary":
        document = source.read(ENDPOINT_SUMMARY, params)
        return build_summary_report(document, requested=params, source_label=source.label)
    if args.verify_command == "limits":
        document = source.read(ENDPOINT_SUMMARY, params)
        return build_limits_report(document, requested=params, source_label=source.label)
    if args.verify_command == "health":
        return build_health_report(
            source.read(ENDPOINT_SUMMARY, params),
            source.read(ENDPOINT_HEALTH, {}),
            requested=params,
            source_label=source.label,
        )
    if args.verify_command == "parity":
        return build_parity_report(
            source.read(ENDPOINT_SUMMARY, params),
            source.read(ENDPOINT_MOBILE_SUMMARY, params),
            requested=params,
            source_label=source.label,
        )
    raise ReadSourceError(f"未知子命令: {args.verify_command}")


def _render(report: Dict[str, Any]) -> str:
    if report["command"] == "summary":
        return render_summary(report)
    if report["command"] == "limits":
        return render_limits(report)
    if report["command"] == "health":
        return render_health(report)
    if report["command"] == "parity":
        return render_parity(report)
    raise ReadSourceError(f"未知子命令: {report['command']}")
