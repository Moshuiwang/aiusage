"""额度观测走本地 outbox 的可靠投递（Issue #87）。

#73 把 outbox 的能力建好了（`collector_store.py`：TTL、去重、退避、磁盘上限、
终态/可重试分类），但 `limits_push.py` 一直自己 `urlopen` 直推，**没有任何调用方**用到
limit observations 那半个范围。结果是：断网期间用量事实不丢、额度观测照丢。

本文件守的是接线后的行为：

- 断网 → 观测落盘，网络恢复后补推；
- TTL 到期的旧观测**不盲目补发**，重新采集；
- 同一组槽位只留最新观测，不同槽位互不顶替；
- 终态错误进死信、可重试错误留在队列，与 usage facts **共用同一套分类**；
- 已回退到直推（`enabled=False`）但磁盘上还有未交付数据时，拒绝静默绕过。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_usage_widget.collector_store import (
    CollectorStore,
    OutboxConfig,
)
from ai_usage_widget.limits_push import deliver_limits_payload, limits_dedupe_key


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeTransport:
    """按剧本回应的投递通道：(status_code, response_json)，或抛异常表示网络不通。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, url: str, token: str, payload: dict, timeout: float):
        self.calls.append(payload)
        outcome = self.script.pop(0) if self.script else (200, {"status": "accepted", "windows_written": 0})
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _payload(*slots: tuple[str, str, str], observed_at: str = "2026-06-03T11:00:00+08:00") -> dict:
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "timezone": "Asia/Shanghai",
        "windows": [
            {
                "source_id": source_id,
                "provider": provider,
                "window": window,
                "used_percent": 40,
                "remaining_percent": 60,
                "observed_at": observed_at,
                "source_type": "runtime_api",
                "confidence": "observed",
                "status": "ok",
            }
            for source_id, provider, window in slots
        ],
    }


class LimitsOutboxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.clock = FakeClock()
        self.outbox_path = str(Path(self._tmp.name) / "outbox.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def config(self, *, enabled: bool = True, ttl: float = 3600.0) -> OutboxConfig:
        return OutboxConfig(enabled=enabled, path=self.outbox_path, limit_ttl_seconds=ttl)

    def store(self) -> CollectorStore:
        return CollectorStore.from_config(self.config(), clock=self.clock)

    def deliver(self, payload: dict, transport: FakeTransport, *, enabled: bool = True, ttl: float = 3600.0) -> dict:
        return deliver_limits_payload(
            "https://example.test/ingest-limits",
            "token",
            payload,
            outbox_config=self.config(enabled=enabled, ttl=ttl),
            transport=transport,
            clock=self.clock,
        )


class TestOfflineThenRecover(LimitsOutboxTestCase):
    def test_offline_observation_is_persisted_instead_of_lost(self) -> None:
        transport = FakeTransport([OSError("network unreachable")])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport)

        self.assertFalse(result["delivered"])
        # 失败原因沿用与用量事实同一套分类，同时必须说清这份观测还在本地。
        self.assertEqual(result["error_type"], "http_request_failed")
        self.assertTrue(result["queued"], "断网时必须明确告诉运维数据还在本地")
        with self.store() as store:
            self.assertEqual(store.pending_count(), 1, "断网时额度观测没有落盘，就是丢了")

    def test_queued_observation_is_pushed_after_network_recovers(self) -> None:
        offline = FakeTransport([OSError("network unreachable")])
        self.deliver(_payload(("codex-main", "codex", "session")), offline)
        # 失败会进退避：下一轮采集（现实里几分钟后）才轮得到它，这里把时间推过去。
        self.clock.advance(60)

        online = FakeTransport([(200, {"status": "accepted", "windows_written": 1}),
                                (200, {"status": "accepted", "windows_written": 1})])
        result = self.deliver(_payload(("claude-main", "claude", "week")), online)

        self.assertTrue(result["delivered"], result)
        pushed_slots = [
            (window["source_id"], window["window"])
            for call in online.calls
            for window in call["windows"]
        ]
        self.assertIn(("codex-main", "session"), pushed_slots, "断网期间那条观测没有被补推")
        self.assertIn(("claude-main", "week"), pushed_slots)
        with self.store() as store:
            self.assertEqual(store.pending_count(), 0, "全部送达后队列必须清空")

    def test_delivered_result_carries_the_server_response(self) -> None:
        transport = FakeTransport([(200, {"status": "accepted", "windows_written": 3})])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport)

        self.assertTrue(result["delivered"])
        self.assertEqual(result["response"]["windows_written"], 3)
        self.assertEqual(result["outbox"]["pending"], 0)


class TestTimeToLive(LimitsOutboxTestCase):
    def test_expired_observation_is_not_blindly_resent(self) -> None:
        """额度是「当前状态」：补发六小时前的旧百分比会把过期值当成现状展示。"""
        offline = FakeTransport([OSError("network unreachable")])
        self.deliver(_payload(("codex-main", "codex", "session")), offline, ttl=3600.0)

        self.clock.advance(3601)

        online = FakeTransport([(200, {"status": "accepted", "windows_written": 1})])
        self.deliver(_payload(("claude-main", "claude", "week")), online, ttl=3600.0)

        pushed_slots = [
            (window["source_id"], window["window"])
            for call in online.calls
            for window in call["windows"]
        ]
        self.assertNotIn(("codex-main", "session"), pushed_slots, "过期观测被盲目补发了")
        self.assertIn(("claude-main", "week"), pushed_slots, "新观测必须照常送出")
        with self.store() as store:
            self.assertEqual(store.stats()["expired_total"], 1, "过期丢弃必须有计数，否则账面看不出来")

    def test_observation_within_ttl_is_still_resent(self) -> None:
        offline = FakeTransport([OSError("network unreachable")])
        self.deliver(_payload(("codex-main", "codex", "session")), offline, ttl=3600.0)

        self.clock.advance(3599)

        online = FakeTransport([(200, {"status": "accepted"}), (200, {"status": "accepted"})])
        self.deliver(_payload(("claude-main", "claude", "week")), online, ttl=3600.0)

        pushed = [w["source_id"] for call in online.calls for w in call["windows"]]
        self.assertIn("codex-main", pushed, "还没过期的观测必须补推")


class TestDedupe(LimitsOutboxTestCase):
    def test_same_slot_set_keeps_only_the_latest_observation(self) -> None:
        for percent in (10, 20, 30):
            payload = _payload(("codex-main", "codex", "session"))
            payload["windows"][0]["used_percent"] = percent
            self.deliver(payload, FakeTransport([OSError("offline")]))

        with self.store() as store:
            # 每次失败都会进退避，所以这里要看「忽略退避」的全集，否则数到的是 0，
            # 「去重生效」和「一条都没留下」会产生同一个绿。
            pending = store.pending(ignore_backoff=True)
            self.assertEqual(len(pending), 1, "同一组槽位应当只留最新一条")
            self.assertEqual(pending[0].payload["windows"][0]["used_percent"], 30)

    def test_different_slot_sets_do_not_replace_each_other(self) -> None:
        self.deliver(_payload(("codex-main", "codex", "session")), FakeTransport([OSError("offline")]))
        self.deliver(_payload(("claude-main", "claude", "week")), FakeTransport([OSError("offline")]))

        with self.store() as store:
            self.assertEqual(store.pending_count(), 2, "不同 provider 的观测不能互相顶掉")

    def test_dedupe_key_is_derived_from_the_slot_set_not_the_values(self) -> None:
        first = _payload(("codex-main", "codex", "session"))
        second = _payload(("codex-main", "codex", "session"))
        second["windows"][0]["used_percent"] = 99
        self.assertEqual(limits_dedupe_key(first), limits_dedupe_key(second))
        self.assertNotEqual(limits_dedupe_key(first), limits_dedupe_key(_payload(("claude-main", "claude", "week"))))


class TestSharedFailureClassification(LimitsOutboxTestCase):
    """终态 / 可重试的判定必须与 usage facts 共用一套，不另起炉灶。"""

    def test_terminal_contract_error_goes_to_dead_letter(self) -> None:
        transport = FakeTransport([(400, {"error_type": "http_schema_invalid", "message": "bad"})])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport)

        self.assertFalse(result["delivered"])
        with self.store() as store:
            self.assertEqual(store.pending_count(), 0, "终态错误不该永远占着重试队列")
            self.assertEqual(store.dead_letter_count(), 1, "终态错误必须留档，不能静默消失")

    def test_retryable_server_error_stays_queued(self) -> None:
        transport = FakeTransport([(503, {"message": "upstream down"})])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport)

        self.assertFalse(result["delivered"])
        with self.store() as store:
            self.assertEqual(store.pending_count(), 1)
            self.assertEqual(store.dead_letter_count(), 0)


class TestKindIsolation(LimitsOutboxTestCase):
    """用量事实与额度观测**共用同一个库**，但绝不能互相打到对方的端点。

    两者的 outbox 路径都来自设备配置里同一个 `outbox` 块，默认是同一个
    `~/.ai-usage/collector_outbox.sqlite`。补推时如果不按 kind 过滤，
    `push-limits` 会把排队中的用量事实 POST 到 `/ingest-limits`，服务端回 400，
    分类判成终态 → 进死信表，**一条已经安全落盘的用量事实就此永远不会再补推**。
    方向正好和 outbox 要解决的问题相反。
    """

    def _enqueue_usage(self) -> None:
        with self.store() as store:
            store.enqueue({"schema_version": 1, "source_id": "linux-dev-bob", "usage_daily": [{"agent": "codex"}]})

    def test_limits_flush_never_touches_queued_usage_facts(self) -> None:
        self._enqueue_usage()

        transport = FakeTransport([(200, {"status": "accepted", "windows_written": 1})])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport)

        self.assertTrue(result["delivered"], result)
        for call in transport.calls:
            self.assertIn("windows", call, "额度补推把用量事实也打到 /ingest-limits 了")
            self.assertNotIn("usage_daily", call)
        with self.store() as store:
            self.assertEqual(store.dead_letter_count(), 0, "用量事实被额度补推打进了死信")
            kinds = [entry.kind for entry in store.pending(ignore_backoff=True)]
            self.assertEqual(kinds, ["usage"], "用量事实必须原封不动留在队列里等 push 补推")

    def test_drain_checks_still_see_every_kind(self) -> None:
        """按 kind 过滤的只有补推。排空判据必须仍然看全部——漏看一种就等于放行未交付数据。"""
        self._enqueue_usage()
        self.deliver(_payload(("codex-main", "codex", "session")), FakeTransport([OSError("offline")]))

        with self.store() as store:
            self.assertEqual(store.undelivered_count(), 2)
            self.assertEqual(len(store._undelivered_records()), 2)


class TestFallbackToDirectPush(LimitsOutboxTestCase):
    def test_disabled_outbox_with_undelivered_data_refuses_to_bypass(self) -> None:
        """回退到直推不允许静默丢弃：磁盘上还有没交付的观测就当场停下。"""
        self.deliver(_payload(("codex-main", "codex", "session")), FakeTransport([OSError("offline")]))

        transport = FakeTransport([(200, {"status": "accepted"})])
        result = self.deliver(_payload(("claude-main", "claude", "week")), transport, enabled=False)

        self.assertFalse(result["delivered"])
        self.assertEqual(result["error_type"], "outbox_not_drained")
        self.assertEqual(transport.calls, [], "被拦下就不该真的发出去")

    def test_disabled_outbox_with_clean_disk_pushes_directly(self) -> None:
        transport = FakeTransport([(200, {"status": "accepted", "windows_written": 1})])
        result = self.deliver(_payload(("codex-main", "codex", "session")), transport, enabled=False)

        self.assertTrue(result["delivered"])
        self.assertEqual(len(transport.calls), 1)

    def test_no_outbox_config_keeps_the_direct_push_behaviour(self) -> None:
        """从没启用过 outbox 的设备：行为零变化，不许因为本次改动多出一个本地库。"""
        transport = FakeTransport([(200, {"status": "accepted", "windows_written": 2})])
        result = deliver_limits_payload(
            "https://example.test/ingest-limits",
            "token",
            _payload(("codex-main", "codex", "session")),
            outbox_config=None,
            transport=transport,
            clock=self.clock,
        )

        self.assertTrue(result["delivered"])
        self.assertEqual(result["response"]["windows_written"], 2)
        self.assertNotIn("outbox", result)
        self.assertFalse(Path(self.outbox_path).exists(), "没有 outbox 配置就不该建库")


if __name__ == "__main__":
    unittest.main()
