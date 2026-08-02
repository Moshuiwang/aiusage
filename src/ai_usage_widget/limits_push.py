"""官方额度观测的上报通道。

历史上这里只有一条直推路径（`urlopen` 打 `/ingest-limits`），断网就丢。#73 建好的
本地 outbox 只接了用量事实，额度观测那半个范围**有能力没有调用方**——
断网期间用量不丢、额度照丢。#87 把它接上：额度观测同样先落盘再补推。

额度与用量事实的可靠性语义**不一样**，接线时必须保留这个区别：

- 用量事实是历史，永远值得补发，所以不设 TTL、绝不去重。
- 额度是**当前状态**。补发六小时前的百分比会把过期值当成现状展示，比没有更糟。
  所以额度观测带 TTL（过期就重新采集，不盲目补发），并按「槽位集合」去重——
  同一组 (source_id, provider, window) 的旧观测被最新的替换。

终态 / 可重试的判定与用量事实**共用同一份** `classify_delivery`，不另起一套。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib import error, request

from .collector_store import (
    DELIVERED,
    KIND_LIMITS,
    TERMINAL,
    CollectorStore,
    OutboxConfig,
    OutboxFull,
    OutboxNotDrained,
    classify_delivery,
)
from .http_identity import PRODUCT_USER_AGENT

Transport = Callable[[str, str, Dict[str, Any], float], Tuple[int, Dict[str, Any]]]


def post_limits_payload(
    url: str, token: str, payload: Dict[str, Any], timeout: float = 10.0
) -> Tuple[int, Dict[str, Any]]:
    """打一次 `/ingest-limits`，返回 (status_code, 响应 JSON)。

    HTTP 错误**不抛异常**：投递结局由 `classify_delivery` 统一判定。在这一层就把
    「服务端拒收」和「网络不通」混成同一个异常，上层就没法区分「重发还有可能被收下」
    和「重发一万次也不会变」。网络层异常照常向上抛。
    """
    if not url:
        raise ValueError("push url is required")
    if not token:
        raise ValueError("push token is required")

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": PRODUCT_USER_AGENT,
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            # 没抛 HTTPError 就说明是 2xx/3xx。`status` 是 http.client.HTTPResponse 的属性，
            # 但 urlopen 也可能返回别的 file-like 对象（老 handler、测试替身），
            # 取不到时按 200 处理——这一层永远拿不到 4xx/5xx，它们走 HTTPError 分支。
            status = getattr(response, "status", None) or getattr(response, "code", None) or 200
            return int(status), _parse_body(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = _parse_body(raw)
        except ValueError:
            parsed = {"message": _safe_response_message(raw)}
        return int(exc.code), parsed


def push_limits_payload(url: str, token: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    """直推一次并返回服务端 JSON；非 200 或响应不合法时抛 `ValueError`。

    这是**没有配置过 outbox 的设备**走的路径，对外行为与 #87 之前一致。
    """
    try:
        status_code, parsed = post_limits_payload(url, token, payload, timeout=timeout)
    except error.URLError as exc:
        raise ValueError(f"limits push failed: {exc.reason}") from exc

    if status_code != 200:
        message = parsed.get("message") if isinstance(parsed, dict) else None
        raise ValueError(
            f"limits push failed with HTTP {status_code}: {_safe_response_message(str(message or parsed))}"
        )
    return parsed


def limits_dedupe_key(payload: Dict[str, Any]) -> str:
    """额度观测的去重键：这批 payload 覆盖的**槽位集合**。

    不能用固定的一个键——`push-limits --provider codex` 与 `--provider claude`
    是两批不同的观测，用同一个键会让后一次把前一次顶掉，等于丢数据。
    也不能把百分比算进去——那样每次采集都是新键，去重完全失效，
    断网一晚上会攒下几百条早已过期的旧值。
    """
    windows = payload.get("windows")
    slots = sorted(
        f"{window.get('source_id')}|{window.get('provider')}|{window.get('window')}"
        for window in (windows if isinstance(windows, list) else [])
        if isinstance(window, dict)
    )
    digest = hashlib.sha256("\n".join(slots).encode("utf-8")).hexdigest()[:16]
    return f"limits:{digest}"


def deliver_limits_payload(
    url: str,
    token: str,
    payload: Dict[str, Any],
    *,
    outbox_config: Optional[OutboxConfig] = None,
    timeout: float = 10.0,
    transport: Optional[Transport] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """投递一份额度观测，按设备配置决定走 outbox 还是直推。

    返回值固定带 `delivered`（这次到底有没有送到服务端）。**队列化不算送达**——
    把「已落盘等补推」报成成功，正是这类可靠投递最容易出的假绿。
    """
    send: Transport = transport or post_limits_payload

    if outbox_config is None:
        # 从没启用过 outbox 的设备：连库文件都不该被建出来。
        return _direct(send, url, token, payload, timeout)

    if not outbox_config.enabled:
        # 已回退到直推。回退**不允许静默丢弃**：磁盘上还有未交付数据就当场停下，
        # 而不是绕过它继续直推——那些观测没人会再看一眼。
        blocked = _drain_guard(outbox_config, clock)
        if blocked is not None:
            return blocked
        return _direct(send, url, token, payload, timeout)

    store = CollectorStore.from_config(outbox_config, clock=clock)
    try:
        store.purge_expired()
        entry_id = _enqueue(store, payload, outbox_config, send, url, token, timeout)
        if entry_id is None:
            return {
                "delivered": False,
                "queued": False,
                "error_type": "outbox_full",
                "error_message": (
                    "本地 outbox 已达磁盘上限，本次额度观测未缓冲也未送达。"
                    f"请先恢复网络排空积压，或导出后处理：{store.path}"
                ),
                "outbox": store.stats(),
            }

        outcomes = _flush(store, send, url, token, timeout, outbox_config.max_flush_batch)
        outcome = outcomes.get(entry_id)
        if outcome is not None and outcome.get("delivered"):
            result: Dict[str, Any] = {"delivered": True, "queued": False, "response": outcome["response"]}
        elif outcome is not None:
            # 失败原因用与用量事实同一套分类（http_request_failed / 服务端 error_type），
            # 但要另外说清「这份观测还在不在本地」——只报失败原因会让人以为它丢了，
            # 只报「已入队」又会盖掉真正的失败形态（比如认证挂了）。两个都给。
            result = {
                "delivered": False,
                "queued": _still_queued(store, entry_id),
                "error_type": outcome["error_type"],
                "error_message": outcome["error_message"],
            }
        else:
            result = {
                "delivered": False,
                "queued": True,
                "error_type": "outbox_queued",
                "error_message": (
                    "本次额度观测已持久化到本地 outbox，等待网络恢复后补推；本次未送达服务端"
                ),
            }
        result["outbox"] = store.stats()
        return result
    finally:
        store.close()


def _still_queued(store: CollectorStore, entry_id: int) -> bool:
    """这份观测是不是还留在本地等补推（退避中也算）。死信不算——它已经不会再发了。"""
    return any(
        entry.entry_id == entry_id
        for entry in store.pending(ignore_backoff=True, kind=KIND_LIMITS)
    )


def _direct(
    send: Transport, url: str, token: str, payload: Dict[str, Any], timeout: float
) -> Dict[str, Any]:
    try:
        status_code, parsed = send(url, token, payload, timeout)
    except Exception as exc:  # noqa: BLE001 - 网络层异常形态很多，统一按投递失败处理
        return {
            "delivered": False,
            "queued": False,
            "error_type": "http_request_failed",
            "error_message": f"limits push failed: {exc}",
        }
    if classify_delivery(status_code, parsed) == DELIVERED:
        return {"delivered": True, "queued": False, "response": parsed}
    # 直推路径没有本地副本：失败就是失败，`queued` 恒为 False，不要让调用方误以为还能补推。
    return {
        "delivered": False,
        "queued": False,
        "error_type": _error_type(status_code, parsed),
        "error_message": _error_message(status_code, parsed),
    }


def _enqueue(
    store: CollectorStore,
    payload: Dict[str, Any],
    outbox_config: OutboxConfig,
    send: Transport,
    url: str,
    token: str,
    timeout: float,
) -> Optional[int]:
    """先落盘。放不下时先尽力排空腾地方，仍然放不下就显式失败。"""
    kwargs: Dict[str, Any] = {
        "kind": KIND_LIMITS,
        "dedupe_key": limits_dedupe_key(payload),
        "ttl_seconds": outbox_config.limit_ttl_seconds,
    }
    try:
        return store.enqueue(payload, **kwargs)
    except OutboxFull:
        _flush(store, send, url, token, timeout, outbox_config.max_flush_batch)
        try:
            return store.enqueue(payload, **kwargs)
        except OutboxFull:
            return None


def _flush(
    store: CollectorStore,
    send: Transport,
    url: str,
    token: str,
    timeout: float,
    limit: Optional[int],
) -> Dict[int, Dict[str, Any]]:
    """按入队顺序补推，返回每个条目各自的结局。

    遇到可重试失败就**停下**：网络不通时继续硬打后面几十条只会拖长采集耗时，
    而它们下一轮还在。终态失败则跳过该条继续——一条永远收不下的 payload
    不该把它后面的观测一起堵死。
    """
    outcomes: Dict[int, Dict[str, Any]] = {}
    for entry in store.pending(limit=limit, kind=KIND_LIMITS):
        try:
            status_code, parsed = send(url, token, entry.payload, timeout)
        except Exception as exc:  # noqa: BLE001
            outcomes[entry.entry_id] = {
                "delivered": False,
                "error_type": "http_request_failed",
                "error_message": f"limits push failed: {exc}",
            }
            store.record_failure(entry.entry_id, f"http_request_failed: {exc}")
            break

        verdict = classify_delivery(status_code, parsed)
        if verdict == DELIVERED:
            outcomes[entry.entry_id] = {"delivered": True, "response": parsed}
            store.ack(entry.entry_id)
            continue

        reason = f"{_error_type(status_code, parsed)}: {_error_message(status_code, parsed)}"
        outcomes[entry.entry_id] = {
            "delivered": False,
            "error_type": _error_type(status_code, parsed),
            "error_message": _error_message(status_code, parsed),
        }
        if verdict == TERMINAL:
            store.dead_letter(entry.entry_id, reason=reason)
            continue
        store.record_failure(entry.entry_id, reason)
        break
    return outcomes


def _drain_guard(outbox_config: OutboxConfig, clock: Callable[[], float]) -> Optional[Dict[str, Any]]:
    """回退到直推前的排空检查。返回 ``None`` 表示放行。"""
    if not Path(outbox_config.path).expanduser().exists():
        return None
    store = CollectorStore.from_config(outbox_config, clock=clock)
    try:
        store.assert_drained()
    except OutboxNotDrained as exc:
        return {
            "delivered": False,
            "queued": False,
            "error_type": "outbox_not_drained",
            "error_message": str(exc),
        }
    finally:
        store.close()
    return None


def _error_type(status_code: Optional[int], parsed: Dict[str, Any]) -> str:
    declared = parsed.get("error_type") if isinstance(parsed, dict) else None
    if isinstance(declared, str) and declared:
        return declared
    if status_code == 401:
        return "http_auth_failed"
    if status_code == 403:
        return "http_access_blocked"
    return "http_status_not_ok"


def _error_message(status_code: Optional[int], parsed: Dict[str, Any]) -> str:
    message = parsed.get("message") if isinstance(parsed, dict) else None
    return _safe_response_message(f"HTTP {status_code}: {message or parsed}")


def _parse_body(body: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("limits push response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("limits push response must be a JSON object")
    return parsed


def _safe_response_message(body: str) -> str:
    message = body.replace("\n", " ").strip()
    return message[:300]
