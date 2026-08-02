"""Issue #73 A 组：采集端本地 outbox（`collector_store.py`）的模块级测试。

被守护的用户结果：**设备断网、日志被回收、长期离线之后，期间的用量事实仍然存在**，
而不是依赖「故障别超过 48 小时」的运气。

本模块只测 store 本身（入队 / ACK / 原子性 / 磁盘上限 / TTL / 退避 / 排空），
端到端补推走 `tests/test_pusher_outbox.py`。

两条写法上的硬要求（AGENTS.md「测试自身也会骗人」）：

- 原子性不接受「现在是绿的」：下面两条原子性测试都**真的在事务中途注入故障**，
  再断言磁盘上没有留下半个状态。
- 磁盘上限不接受「抛了异常就算过」：还必须断言**已有条目一条不少、逐字节未变**，
  否则「拒绝新增」实现成「悄悄丢最旧」也能让异常断言变绿。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget.collector_store import (
    DELIVERED,
    KIND_LIMITS,
    KIND_USAGE,
    RETRY,
    TERMINAL,
    CollectorStore,
    OutboxConfig,
    OutboxFull,
    OutboxNotDrained,
    classify_delivery,
)
from ai_usage_widget.config import ConfigError, validate_device_config
from ai_usage_widget.version_contract import UNSUPPORTED_ERROR_TYPE


class FakeClock:
    """虚拟时钟。断网 72 小时这种场景不可能靠真实等待验证。"""

    def __init__(self, now: float = 1_780_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _payload(marker: str, filler: int = 0) -> dict:
    return {
        "schema_version": 1,
        "source_id": "linux-dev",
        "collection_window": "daily",
        "marker": marker,
        "usage_daily": [{"period": "2026-08-01", "agent": "codex", "totalTokens": 1}],
        "filler": "x" * filler,
    }


class CollectorStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "data" / "collector_outbox.sqlite"
        self.clock = FakeClock()

    def open_store(self, **kwargs) -> CollectorStore:
        store = CollectorStore(self.db_path, clock=self.clock, **kwargs)
        self.addCleanup(store.close)
        return store


class TestEnqueueAndAck(CollectorStoreTestCase):
    def test_pending_payload_round_trips_byte_identically(self) -> None:
        """payload 语义零变化：进 outbox 再出来必须和进去时完全一致。

        补推发出去的就是这个 dict，它一旦在存储层被改写（丢 None、数字变字符串、
        中文被转义成 \\uXXXX），服务端收到的就不再是采集端真正观测到的东西。
        """
        store = self.open_store()
        original = _payload("往返")
        original["ai_account"] = {"display_name": None, "subscription": "pro"}
        original["float_field"] = 1.5

        store.enqueue(original)
        entries = store.pending()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].payload, original)
        self.assertEqual(entries[0].kind, KIND_USAGE)

    def test_unacked_payload_survives_process_restart(self) -> None:
        """进程被杀 / 机器重启后，没 ACK 的数据必须还在——这就是 outbox 的全部意义。"""
        first = self.open_store()
        first.enqueue(_payload("重启前"))
        first.close()

        reopened = self.open_store()

        self.assertEqual([e.payload["marker"] for e in reopened.pending()], ["重启前"])

    def test_ack_removes_the_entry_permanently(self) -> None:
        store = self.open_store()
        entry_id = store.enqueue(_payload("已送达"))

        store.ack(entry_id)
        store.close()

        reopened = self.open_store()
        self.assertEqual(reopened.pending(), [])
        self.assertEqual(reopened.pending_count(), 0)
        self.assertEqual(reopened.stats()["delivered_total"], 1)

    def test_usage_entries_never_expire(self) -> None:
        """usage facts 是「持久补推直到明确 ACK」，不许被 TTL 顺手清掉。"""
        store = self.open_store()
        store.enqueue(_payload("一年前"))

        self.clock.advance(365 * 24 * 3600)

        self.assertEqual(store.purge_expired(), 0)
        self.assertEqual(len(store.pending()), 1)
        self.assertIsNone(store.pending()[0].expires_at)


class TestAtomicity(CollectorStoreTestCase):
    """写 outbox 与 ACK 状态必须原子——用真实故障注入证明，不是「现在是绿的」。"""

    def test_ack_and_its_receipt_commit_or_roll_back_together(self) -> None:
        """ACK = 删除条目 + 记一笔投递回执。中途崩溃时两者必须一起回滚。

        若不在同一事务里，崩在中间会得到「条目已删、回执没记」——
        数据永久消失且账面看不出来，正是本 Issue 要消灭的静默丢失。
        """
        store = self.open_store()
        entry_id = store.enqueue(_payload("原子 ACK"))

        boom = RuntimeError("模拟 ACK 写回执时进程被杀")
        with patch.object(CollectorStore, "_record_ack_receipt", side_effect=boom):
            with self.assertRaises(RuntimeError):
                store.ack(entry_id)

        store.close()
        reopened = self.open_store()
        self.assertEqual(
            [e.payload["marker"] for e in reopened.pending()],
            ["原子 ACK"],
            "ACK 事务没有回滚：条目已经消失，但回执没写成——数据被静默吞掉了",
        )
        self.assertEqual(reopened.stats()["delivered_total"], 0)

    def test_dedupe_replacement_commits_or_rolls_back_together(self) -> None:
        """按 dedupe_key 替换 = 删旧 + 插新。崩在中间时旧观测必须还在。"""
        store = self.open_store(limit_ttl_seconds=3600.0)
        store.enqueue(_payload("旧观测"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=3600.0)

        boom = RuntimeError("模拟替换时进程被杀")
        with patch.object(CollectorStore, "_insert_entry", side_effect=boom):
            with self.assertRaises(RuntimeError):
                store.enqueue(
                    _payload("新观测"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=3600.0
                )

        store.close()
        reopened = self.open_store()
        self.assertEqual(
            [e.payload["marker"] for e in reopened.pending()],
            ["旧观测"],
            "替换事务没有回滚：旧观测被删了、新观测没写进去，两头落空",
        )

    def test_a_half_written_transaction_leaves_no_partial_row(self) -> None:
        """入队本身也必须原子：崩在计数与插入之间不许留下半条记录。"""
        store = self.open_store()
        with patch.object(CollectorStore, "_bump_counter", side_effect=RuntimeError("崩")):
            with self.assertRaises(RuntimeError):
                store.enqueue(_payload("半条"))

        store.close()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        self.assertEqual(rows, 0, "事务没回滚，磁盘上留下了半条记录")


class TestDiskCap(CollectorStoreTestCase):
    """磁盘上限策略：**拒绝新增**，绝不丢最旧。

    理由写在 `collector_store.py` 的模块 docstring 里，这里守住它的可观测后果：
    上限触发时调用方拿到显式失败，而**历史一条不少**。
    """

    def _fill_to_cap(self, store: CollectorStore, count: int, filler: int) -> list[str]:
        markers = []
        for index in range(count):
            marker = f"历史-{index}"
            store.enqueue(_payload(marker, filler=filler))
            markers.append(marker)
        return markers

    def test_cap_rejects_the_new_entry_and_keeps_every_existing_one(self) -> None:
        store = self.open_store(max_bytes=4096)
        markers = self._fill_to_cap(store, count=3, filler=800)
        before = [json.dumps(e.payload, sort_keys=True) for e in store.pending()]

        with self.assertRaises(OutboxFull):
            store.enqueue(_payload("新数据", filler=2000))

        after = [json.dumps(e.payload, sort_keys=True) for e in store.pending()]
        self.assertEqual(
            [e.payload["marker"] for e in store.pending()],
            markers,
            "上限触发时丢了历史条目——那是把「静默丢历史」重新引了回来",
        )
        self.assertEqual(after, before, "历史条目被改写了")

    def test_cap_rejection_is_visible_in_the_error(self) -> None:
        store = self.open_store(max_bytes=4096)
        self._fill_to_cap(store, count=3, filler=800)
        with self.assertRaises(OutboxFull) as ctx:
            store.enqueue(_payload("新数据", filler=2000))
        message = str(ctx.exception)
        self.assertIn("4096", message)
        self.assertIn(str(store.used_bytes()), message)

    def test_room_frees_up_after_acking(self) -> None:
        """上限不是死锁：网络恢复、旧条目 ACK 之后必须能重新写入。"""
        store = self.open_store(max_bytes=4096)
        self._fill_to_cap(store, count=3, filler=800)
        with self.assertRaises(OutboxFull):
            store.enqueue(_payload("新数据", filler=2000))

        for entry in store.pending():
            store.ack(entry.entry_id)

        store.enqueue(_payload("新数据", filler=2000))
        self.assertEqual([e.payload["marker"] for e in store.pending()], ["新数据"])

    def test_dead_letters_count_against_the_cap(self) -> None:
        """终态失败的 payload 留档也占空间，不许把它变成不受控增长的后门。"""
        store = self.open_store(max_bytes=8192)
        entry_id = store.enqueue(_payload("终态", filler=2000))
        store.dead_letter(entry_id, reason="http_schema_invalid")
        self.assertGreater(store.used_bytes(), 2000)
        self.assertEqual(store.dead_letter_count(), 1)


class TestLimitObservationTTL(CollectorStoreTestCase):
    """limit observations 带 TTL：只补最新有效观测，过期的重新采集而不是盲目补发旧值。"""

    def test_expired_limit_observation_is_not_pending_and_is_counted_when_purged(self) -> None:
        store = self.open_store()
        store.enqueue(_payload("额度旧值"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=3600.0)

        self.clock.advance(3601)

        self.assertEqual(store.pending(), [], "过期额度观测仍然会被补发出去")
        self.assertEqual(store.purge_expired(), 1)
        self.assertEqual(store.pending_count(), 0)
        self.assertEqual(
            store.stats()["expired_total"],
            1,
            "过期丢弃没有计数——那就是静默丢弃，账面上看不出来",
        )

    def test_not_yet_expired_limit_observation_is_still_pending(self) -> None:
        store = self.open_store()
        store.enqueue(_payload("额度新值"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=3600.0)
        self.clock.advance(3599)
        self.assertEqual([e.payload["marker"] for e in store.pending()], ["额度新值"])

    def test_same_dedupe_key_keeps_only_the_latest_observation(self) -> None:
        store = self.open_store()
        for index in range(3):
            store.enqueue(
                _payload(f"额度-{index}"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=3600.0
            )
            self.clock.advance(60)

        self.assertEqual([e.payload["marker"] for e in store.pending()], ["额度-2"])

    def test_different_dedupe_keys_do_not_replace_each_other(self) -> None:
        store = self.open_store()
        store.enqueue(_payload("codex 额度"), kind=KIND_LIMITS, dedupe_key="codex", ttl_seconds=60)
        store.enqueue(_payload("claude 额度"), kind=KIND_LIMITS, dedupe_key="claude", ttl_seconds=60)
        self.assertEqual(
            sorted(e.payload["marker"] for e in store.pending()),
            ["claude 额度", "codex 额度"],
        )

    def test_usage_entries_are_never_deduped_against_each_other(self) -> None:
        """usage facts 每条都是不同覆盖窗口的事实，任何「只留最新」都是丢数据。"""
        store = self.open_store()
        for index in range(3):
            store.enqueue(_payload(f"小时-{index}"))
        self.assertEqual(len(store.pending()), 3)


class TestBackoff(CollectorStoreTestCase):
    def test_failure_pushes_the_entry_out_of_the_eligible_set_until_backoff_elapses(self) -> None:
        store = self.open_store(backoff_base_seconds=30.0, backoff_cap_seconds=900.0)
        entry_id = store.enqueue(_payload("退避"))

        store.record_failure(entry_id, "http_request_failed: network unreachable")

        self.assertEqual(store.pending(), [], "失败后立刻又被取出重试，等于没有退避")
        self.assertEqual(store.pending_count(), 1, "退避中的条目不算 pending 就是把它弄丢了")
        self.clock.advance(30)
        self.assertEqual(len(store.pending()), 1)

    def test_backoff_grows_exponentially_but_is_capped(self) -> None:
        store = self.open_store(backoff_base_seconds=30.0, backoff_cap_seconds=900.0)
        entry_id = store.enqueue(_payload("退避"))

        delays = []
        for _ in range(8):
            next_at = store.record_failure(entry_id, "boom")
            delays.append(next_at - self.clock())
            self.clock.advance(delays[-1])

        self.assertEqual(delays[:4], [30.0, 60.0, 120.0, 240.0])
        self.assertTrue(all(delay <= 900.0 for delay in delays), delays)
        self.assertEqual(delays[-1], 900.0, "退避没有封顶，离线久了会永远等下去")

    def test_failure_records_attempts_and_last_error(self) -> None:
        store = self.open_store()
        entry_id = store.enqueue(_payload("退避"))
        store.record_failure(entry_id, "http_request_failed: boom")
        self.clock.advance(3600)
        entry = store.pending()[0]
        self.assertEqual(entry.attempts, 1)
        self.assertEqual(entry.last_error, "http_request_failed: boom")

    def test_clear_backoff_makes_every_entry_eligible_again(self) -> None:
        """一条送达就证明网络回来了，其余条目不该继续干等各自的退避。"""
        store = self.open_store()
        ids = [store.enqueue(_payload(f"条目-{i}")) for i in range(3)]
        for entry_id in ids:
            store.record_failure(entry_id, "boom")
        self.assertEqual(store.pending(), [])

        store.clear_backoff()

        self.assertEqual(len(store.pending()), 3)


class TestDeadLetter(CollectorStoreTestCase):
    def test_dead_letter_keeps_the_payload_out_of_pending_but_on_disk(self) -> None:
        """终态错误不重试，但也**不静默丢弃**：payload 连同原因一起留档，可导出。"""
        store = self.open_store()
        entry_id = store.enqueue(_payload("终态"))

        store.dead_letter(entry_id, reason="http_schema_invalid: usage_daily must be a list")

        self.assertEqual(store.pending(), [])
        self.assertEqual(store.dead_letter_count(), 1)
        records = store.dead_letters()
        self.assertEqual(records[0]["payload"]["marker"], "终态")
        self.assertIn("http_schema_invalid", records[0]["reason"])

    def test_dead_letters_survive_restart(self) -> None:
        store = self.open_store()
        store.dead_letter(store.enqueue(_payload("终态")), reason="bad")
        store.close()
        self.assertEqual(self.open_store().dead_letter_count(), 1)


class TestClassifyDelivery(unittest.TestCase):
    """终态 vs 可重试的判定口径。判错方向都很贵：

    - 该重试的判成终态 → 一次 5xx 就把数据扔进死信，正是 outbox 要防的丢失；
    - 该终态的判成重试 → 一条永远被 400 拒收的 payload 卡住整个队列。
    """

    def test_network_exception_is_retryable(self) -> None:
        self.assertEqual(classify_delivery(None, None, exception=OSError("unreachable")), RETRY)

    def test_http_200_is_delivered(self) -> None:
        self.assertEqual(classify_delivery(200, {"status": "accepted"}), DELIVERED)

    def test_contract_errors_are_terminal(self) -> None:
        for status_code in (400, 409, 413, 422):
            with self.subTest(status_code=status_code):
                self.assertEqual(classify_delivery(status_code, {}), TERMINAL)

    def test_version_incompatibility_is_terminal_even_with_http_200(self) -> None:
        """服务端可以用 200 带 `error_type` 表达版本不兼容；重发同一份也永远不会被收。"""
        self.assertEqual(
            classify_delivery(200, {"error_type": UNSUPPORTED_ERROR_TYPE}),
            TERMINAL,
        )

    def test_server_side_and_transient_failures_are_retryable(self) -> None:
        for status_code in (429, 500, 502, 503, 504, 401, 403):
            with self.subTest(status_code=status_code):
                self.assertEqual(classify_delivery(status_code, {}), RETRY)


class TestDrainBeforeDisabling(CollectorStoreTestCase):
    """回退演练：关闭 outbox 之前必须排空，不允许静默丢弃。"""

    def test_assert_drained_raises_while_data_is_still_unacked(self) -> None:
        store = self.open_store()
        store.enqueue(_payload("未 ACK"))

        with self.assertRaises(OutboxNotDrained) as ctx:
            store.assert_drained()

        message = str(ctx.exception)
        self.assertIn("1", message)
        self.assertIn(str(self.db_path), message)

    def test_assert_drained_also_guards_backed_off_and_dead_lettered_data(self) -> None:
        """退避中的条目和死信同样是「还没交付的数据」，不能因为不在 pending 里就放行。"""
        store = self.open_store()
        backed_off = store.enqueue(_payload("退避中"))
        store.record_failure(backed_off, "boom")
        self.assertEqual(store.pending(), [])
        with self.assertRaises(OutboxNotDrained):
            store.assert_drained()

        store.ack(backed_off)
        store.dead_letter(store.enqueue(_payload("死信")), reason="bad")
        with self.assertRaises(OutboxNotDrained):
            store.assert_drained()

    def test_assert_drained_passes_once_everything_is_acked_or_exported(self) -> None:
        store = self.open_store()
        entry_id = store.enqueue(_payload("待排空"))
        store.ack(entry_id)
        store.assert_drained()

    def test_export_pending_writes_every_undelivered_payload(self) -> None:
        """排空的另一条合法出口：导出后人工处理。导出必须一条不落。"""
        store = self.open_store()
        store.enqueue(_payload("条目-a"))
        backed_off = store.enqueue(_payload("条目-b"))
        store.record_failure(backed_off, "boom")
        store.dead_letter(store.enqueue(_payload("条目-c")), reason="bad")

        dest = self.root / "export.json"
        exported = store.export_undelivered(dest)

        records = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(exported, 3)
        self.assertEqual(
            sorted(record["payload"]["marker"] for record in records),
            ["条目-a", "条目-b", "条目-c"],
        )

    def test_export_does_not_delete_anything_on_its_own(self) -> None:
        """导出不等于丢弃：没有显式 discard 之前，数据必须还在。"""
        store = self.open_store()
        store.enqueue(_payload("条目-a"))
        store.export_undelivered(self.root / "export.json")
        self.assertEqual(store.pending_count(), 1)

    def test_discard_after_export_requires_the_export_to_exist(self) -> None:
        """唯一允许清空的路径是「已导出」，且导出文件必须真的在。"""
        store = self.open_store()
        store.enqueue(_payload("条目-a"))
        with self.assertRaises(OutboxNotDrained):
            store.discard_undelivered(exported_to=self.root / "不存在.json")
        self.assertEqual(store.pending_count(), 1)

        dest = self.root / "export.json"
        store.export_undelivered(dest)
        store.discard_undelivered(exported_to=dest)
        store.assert_drained()

    def test_discard_refuses_when_the_export_does_not_cover_current_data(self) -> None:
        """「导出文件存在」不等于「这份数据被导出过」。

        真实序列：导出 → 又攒了几条新的 → 拿旧导出文件去 discard。
        只校验文件存在的话，那几条**从来没被导出过**的数据会被一起清掉——
        名义上「导出后丢弃」，实际上是静默丢弃。上一轮遗留的陈旧导出文件同理。
        """
        store = self.open_store()
        store.enqueue(_payload("已导出"))
        dest = self.root / "export.json"
        store.export_undelivered(dest)

        store.enqueue(_payload("导出之后才来的"))

        with self.assertRaises(OutboxNotDrained) as ctx:
            store.discard_undelivered(exported_to=dest)
        self.assertIn("导出", str(ctx.exception))
        self.assertEqual(store.pending_count(), 2, "校验失败却已经把数据删了")

        store.export_undelivered(dest)
        store.discard_undelivered(exported_to=dest)
        store.assert_drained()


class TestOutboxConfigParsing(unittest.TestCase):
    BASE = {
        "source_id": "linux-dev",
        "server_url": "https://example.invalid/ingest",
        "timezone": "Asia/Shanghai",
        "platform": "linux",
    }

    def test_absent_outbox_config_means_legacy_direct_push(self) -> None:
        """没配 outbox 的设备行为必须一个字节都不变。"""
        self.assertIsNone(validate_device_config(dict(self.BASE)).outbox)

    def test_outbox_config_is_parsed_with_defaults(self) -> None:
        config = validate_device_config({**self.BASE, "outbox": {"enabled": True}})
        self.assertIsInstance(config.outbox, OutboxConfig)
        self.assertTrue(config.outbox.enabled)
        self.assertTrue(config.outbox.path)
        self.assertGreater(config.outbox.max_bytes, 0)

    def test_outbox_can_be_declared_but_disabled(self) -> None:
        """回退开关：声明存在但关闭——pusher 据此知道要先检查有没有未排空数据。"""
        config = validate_device_config(
            {**self.BASE, "outbox": {"enabled": False, "path": "/var/tmp/x.sqlite"}}
        )
        self.assertIsNotNone(config.outbox)
        self.assertFalse(config.outbox.enabled)
        self.assertEqual(config.outbox.path, "/var/tmp/x.sqlite")

    def test_relative_paths_are_rejected(self) -> None:
        """相对路径 = 换个 cwd 就换一个库，缓冲了三天的数据从此没人再读。

        采集是 LaunchAgent / systemd 拉起的，cwd 通常是 `/` 或 `$HOME`，
        和人在仓库根手工执行时**不是同一个目录**。这种丢失在账面上完全看不出来，
        正是本 Issue 要消灭的东西，所以在配置解析阶段就必须响亮地拒绝。
        """
        with self.assertRaises(ConfigError):
            validate_device_config(
                {**self.BASE, "outbox": {"enabled": True, "path": "data/outbox.sqlite"}}
            )

    def test_home_relative_paths_are_expanded_to_absolute(self) -> None:
        config = validate_device_config(
            {**self.BASE, "outbox": {"enabled": True, "path": "~/.ai-usage/x.sqlite"}}
        )
        self.assertTrue(Path(config.outbox.path).is_absolute())
        self.assertNotIn("~", config.outbox.path)

    def test_the_default_path_is_absolute_and_per_os_user(self) -> None:
        """默认值自己也必须过这一关，否则「不配 path 就中招」。"""
        config = validate_device_config({**self.BASE, "outbox": {"enabled": True}})
        self.assertTrue(Path(config.outbox.path).is_absolute())
        self.assertTrue(config.outbox.path.startswith(str(Path.home())))

    def test_invalid_outbox_config_is_rejected_loudly(self) -> None:
        for bad in ({"enabled": True, "max_bytes": 0}, {"enabled": True, "path": ""}, []):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError):
                    validate_device_config({**self.BASE, "outbox": bad})


if __name__ == "__main__":
    unittest.main()
