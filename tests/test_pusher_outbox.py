"""Issue #73 B 组：断网→恢复→补推的端到端行为（`pusher.py` × `collector_store.py`）。

用户结果：**设备断网 72 小时、本地日志已被回收，恢复后期间的用量事实仍然完整到云端。**

本模块的三条写法约束（AGENTS.md「测试自身也会骗人」）：

1. 「断网 72 小时」必须真的超出 48h 回扫窗口，而且**本地采集器每次只吐出当前那一小时**——
   模拟日志被回收。这样一来，恢复时的一次回扫在结构上不可能补回历史；能补回来只可能
   是 outbox 干的。`test_without_outbox_the_same_script_loses_every_offline_hour` 是这条的
   反证：同一份脚本关掉 outbox，服务端只剩恢复那一小时。没有这条对照，本组测试测的就是
   「现有回扫能力」而不是 outbox。
2. 幂等与完整性一律**从产物独立算一遍**：期望值由本模块按自己脚本里的小时表和 token 表
   算出，实际值由 mock ingest 收到的事实**在本模块里**重新汇总。全程不调用被测代码的
   任何统计函数，也不拿 pusher 的返回值当账。
3. mock ingest 的幂等口径抄的是服务端真实自然键（`write-model.ts` 里
   `ON CONFLICT(source_id, agent, client, window_start, window_end, ai_provider,
   ai_account_id, attribution_confidence, provenance)`），不是 `fact_id` 字符串——
   拿 pusher 自己拼的 `fact_id` 当键会让「pusher 和自己比对」，测不出东西。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget.collector_store import KIND_LIMITS, CollectorStore, OutboxConfig
from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.models import CommandResult
from ai_usage_widget.pusher import DevicePusher, IngestHTTPClient
from ai_usage_widget.version_contract import UNSUPPORTED_ERROR_TYPE


class FakeClock:
    """虚拟时钟。断网 72 小时这种场景不可能靠真实等待验证。

    刻意不从 `test_collector_store` import：跨测试模块的 import 会让本模块只能在
    discovery 里跑，单独跑一个类时直接 ImportError——而单独跑某个类正是变异验证的
    常用姿势，那时看到的「红」是加载失败，不是守卫生效，两者会被混为一谈。
    """

    def __init__(self, now: float = 1_780_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


TZ = timezone(timedelta(hours=8))
BASE_HOUR = datetime(2026, 7, 20, 0, 0, 0, tzinfo=TZ)

#: 本模块自己的「事实脚本」。期望值只从这两个函数算，不从被测代码算。
OFFLINE_HOURS = 72


def hour_iso(index: int) -> str:
    return (BASE_HOUR + timedelta(hours=index)).isoformat()


def tokens_for(index: int) -> int:
    """每小时一个互不相同的 token 数，任何一小时丢失都会让独立求和对不上。"""
    return 1000 + index * 7


class ScriptedCollector:
    """模拟本机采集：**每次只看得见当前这一小时**。

    这一点是「断网 72 小时」场景的核心。真实世界里 `~/.codex` 日志会被回收、
    `--lookback-hours 48` 也只回扫 48 小时；这里把它压到 1 小时，让
    「恢复时靠回扫补历史」在结构上不可能，从而只留下 outbox 一条通路。
    """

    def __init__(self) -> None:
        self.hour_index = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> CommandResult:
        self.calls.append(list(argv))
        if argv[0] == "ccusage" and argv[1] == "daily":
            return CommandResult(stdout=json.dumps(self._ccusage_daily()), exit_code=0)
        if argv[0] == "ccusage":
            # session / blocks：给个不符合形状的 JSON，pusher 会跳过它们。
            # 本组关心的是 hourly facts，少两个可选报告不影响结论。
            return CommandResult(stdout="{}", exit_code=0)
        if "mswusage-codex" in argv:
            return CommandResult(stdout=json.dumps(self._codex_report()), exit_code=0)
        if "mswusage-claude" in argv:
            return CommandResult(
                exit_code=1, error_type="command_failed", error_message="本场景不采 claude"
            )
        raise AssertionError(f"脚本没有预置这条采集命令：{argv}")

    def _ccusage_daily(self) -> dict:
        return {
            "daily": [
                {
                    "period": "2026-07-20",
                    "agent": "codex",
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "totalTokens": 2,
                }
            ],
            "totals": {"totalTokens": 2},
        }

    def _codex_report(self) -> dict:
        start = hour_iso(self.hour_index)
        end = hour_iso(self.hour_index + 1)
        return {
            "schema_version": 1,
            "source": "mswusage_codex",
            "provenance": "mswusage_codex_token_count",
            "generated_at": end,
            "collector": {
                "version": "test",
                "mode": "incremental",
                "lookback_hours": 48,
                "scan_complete": True,
                "coverage": {"start": start, "end": end},
            },
            "hourly": [
                {
                    "hour": start,
                    "window_end": end,
                    "input_tokens": tokens_for(self.hour_index) - 1,
                    "output_tokens": 1,
                    "total_tokens": tokens_for(self.hour_index),
                    "event_count": 1,
                    "session_count": 1,
                }
            ],
            "daily": [],
            "sessions": [],
        }


class MockIngestServer(IngestHTTPClient):
    """本地 mock ingest：按服务端真实自然键做 coverage window 幂等对账。

    `online=False` 时抛网络异常，模拟断网；`fail_next` 可以脚本化返回值。
    """

    def __init__(self) -> None:
        self.online = True
        self.scripted: list[tuple[int, dict] | Exception] = []
        self.facts: dict[tuple, dict] = {}
        self.received_payloads: list[dict] = []
        self.duplicate_fact_writes = 0
        self.lose_acks = False

    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        if not self.online:
            raise OSError("模拟断网：network is unreachable")
        if self.scripted:
            result = self.scripted.pop(0)
            if isinstance(result, Exception):
                raise result
            status_code, body = result
            self._record_request(data)
            # 被拒的请求什么都没写入——脚本化失败时**不**记账，
            # 否则「400 之后总量还对得上」会因为服务端偷偷收下了而假绿。
            if status_code == 200 and not body.get("error_type"):
                self._absorb_facts(data)
            return result
        self._record_request(data)
        self._absorb_facts(data)
        if self.lose_acks:
            # 服务端已经写入，但 ACK 在回程丢了——采集端只能重发，
            # 这正是幂等性要顶住的场景。
            raise OSError("模拟 ACK 回程丢失")
        return 200, {"status": "accepted", "source_id": data.get("source_id")}

    def _record_request(self, payload: dict) -> None:
        self.received_payloads.append(json.loads(json.dumps(payload)))

    def _absorb_facts(self, payload: dict) -> None:
        for fact in payload.get("usage_hourly_facts", []):
            key = natural_key(payload["source_id"], fact)
            if key in self.facts:
                self.duplicate_fact_writes += 1
            self.facts[key] = fact


def natural_key(source_id: str, fact: dict) -> tuple:
    """服务端 `usage_hourly_facts` 的自然键（write-model.ts 的 ON CONFLICT 列）。"""
    account = fact["ai_account"]
    return (
        source_id,
        fact["agent"],
        fact["client"],
        fact["window_start"],
        fact["window_end"],
        account["provider"],
        account["account_id"],
        fact["attribution_confidence"],
        fact["provenance"],
    )


class PusherOutboxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "data" / "collector_outbox.sqlite"
        self.clock = FakeClock()
        self.server = MockIngestServer()
        self.collector = ScriptedCollector()

    def make_config(self, *, outbox: OutboxConfig | None) -> DeviceConfig:
        return DeviceConfig(
            schema_version=1,
            source_id="outbox-linux-dev",
            host="linux-dev.internal",
            machine="linux-dev",
            os_user="wangzp",
            platform="linux",
            timezone="Asia/Shanghai",
            server_url="https://ingest.example.invalid/ingest",
            timeout_seconds=30,
            token_env=None,
            outbox=outbox,
        )

    def open_store(self, **kwargs) -> CollectorStore:
        store = CollectorStore(self.db_path, clock=self.clock, **kwargs)
        self.addCleanup(store.close)
        return store

    def make_pusher(self, config: DeviceConfig, store: CollectorStore | None) -> DevicePusher:
        return DevicePusher(
            config,
            executor=self.collector,
            http_client=self.server,
            retry_attempts=1,
            retry_sleep=lambda _seconds: None,
            outbox=store,
        )

    # --- 独立复算工具：只用本模块自己的脚本，不碰被测代码 --------------------

    def observed_hours_on_server(self) -> set[str]:
        return {key[3] for key in self.server.facts}

    def observed_total_tokens_on_server(self) -> int:
        return sum(int(fact["usage"]["total_tokens"]) for fact in self.server.facts.values())


class TestSeventyTwoHourOutage(PusherOutboxTestCase):
    def _run_outage_script(self, store: CollectorStore | None, config: DeviceConfig) -> None:
        """断网 72 小时（每小时一次采集上报），第 73 小时恢复。"""
        pusher = self.make_pusher(config, store)
        self.server.online = False
        for index in range(OFFLINE_HOURS):
            self.collector.hour_index = index
            pusher.push()
            self.clock.advance(3600)
        self.server.online = True
        self.collector.hour_index = OFFLINE_HOURS
        pusher.push()

    def test_every_offline_hour_reaches_the_server_after_recovery(self) -> None:
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))

        self._run_outage_script(store, config)

        expected_hours = {hour_iso(index) for index in range(OFFLINE_HOURS + 1)}
        expected_total = sum(tokens_for(index) for index in range(OFFLINE_HOURS + 1))

        self.assertEqual(
            self.observed_hours_on_server(),
            expected_hours,
            "断网期间有小时没能补推回来",
        )
        self.assertEqual(self.observed_total_tokens_on_server(), expected_total)
        self.assertEqual(store.pending_count(), 0, "还有数据卡在 outbox 里没送出去")
        self.assertEqual(store.dead_letter_count(), 0)

    def test_the_outage_really_exceeds_the_48_hour_rescan_window(self) -> None:
        """防呆：本场景必须真的跨过 48 小时，否则测的是现有回扫能力。"""
        span_hours = (
            datetime.fromisoformat(hour_iso(OFFLINE_HOURS))
            - datetime.fromisoformat(hour_iso(0))
        ).total_seconds() / 3600
        self.assertGreater(span_hours, 48.0)

    def test_without_outbox_the_same_script_loses_every_offline_hour(self) -> None:
        """对照组：同一份脚本关掉 outbox，断网期间的小时**全部永久丢失**。

        这条绿了才说明上面那条测的是 outbox，而不是回扫窗口。
        """
        self._run_outage_script(None, self.make_config(outbox=None))

        self.assertEqual(
            self.observed_hours_on_server(),
            {hour_iso(OFFLINE_HOURS)},
            "没有 outbox 却补回了历史小时——说明脚本没有真的模拟日志回收，本组结论不成立",
        )

    def test_recovery_survives_a_process_restart(self) -> None:
        """断网期间进程被重启（LaunchAgent 重新拉起）也不许丢数据。"""
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        self.server.online = False
        for index in range(3):
            self.collector.hour_index = index
            store = CollectorStore(self.db_path, clock=self.clock)
            self.make_pusher(config, store).push()
            store.close()  # 每一轮都换一个进程
            self.clock.advance(3600)

        self.server.online = True
        self.collector.hour_index = 3
        final_store = self.open_store()
        self.make_pusher(config, final_store).push()

        self.assertEqual(
            self.observed_hours_on_server(),
            {hour_iso(index) for index in range(4)},
        )


class TestIdempotentReplay(PusherOutboxTestCase):
    def test_replaying_after_lost_acks_does_not_change_the_reconciled_totals(self) -> None:
        """ACK 丢失导致的重复补推，对账后总量不变。

        期望值来自本模块的小时表 / token 表；实际值由本模块对 mock ingest 的对账产物
        重新汇总。两边都不经过被测代码的任何统计逻辑。
        """
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)

        # 前 3 小时：服务端写入成功，但 ACK 全部在回程丢失 → 采集端会一直重发。
        self.server.lose_acks = True
        for index in range(3):
            self.collector.hour_index = index
            pusher.push()
            self.clock.advance(3600)

        # ACK 恢复：outbox 把这 3 小时又整整重发了一遍。
        self.server.lose_acks = False
        self.collector.hour_index = 3
        pusher.push()

        expected_hours = {hour_iso(index) for index in range(4)}
        expected_total = sum(tokens_for(index) for index in range(4))

        self.assertGreater(
            self.server.duplicate_fact_writes,
            0,
            "服务端根本没收到重复事实，这条幂等测试是空转的",
        )
        self.assertEqual(self.observed_hours_on_server(), expected_hours)
        self.assertEqual(
            self.observed_total_tokens_on_server(),
            expected_total,
            "重复补推之后总量变了——幂等对账没生效",
        )
        self.assertEqual(store.pending_count(), 0)

    def test_a_duplicate_payload_is_not_double_counted_by_the_natural_key(self) -> None:
        """反向防呆：如果 mock ingest 按「每次都新增」记账，上面那条会失效。

        这里直接证明 mock 的对账口径确实会去重，而不是碰巧没收到重复。
        """
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)
        self.collector.hour_index = 0
        pusher.push()
        first_snapshot = self.observed_total_tokens_on_server()

        # 同一小时再采一次、再推一次（真实世界里换一次重叠回扫就会这样）。
        self.collector.hour_index = 0
        pusher.push()

        self.assertEqual(len(self.server.received_payloads), 2)
        self.assertEqual(self.server.duplicate_fact_writes, 1)
        self.assertEqual(self.observed_total_tokens_on_server(), first_snapshot)


class TestErrorClassification(PusherOutboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = self.open_store()
        self.config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        self.pusher = self.make_pusher(self.config, self.store)

    def test_terminal_contract_error_is_dead_lettered_and_never_resent(self) -> None:
        self.server.scripted = [(400, {"error_type": "http_schema_invalid", "message": "bad"})]
        self.collector.hour_index = 0
        result = self.pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(self.store.pending_count(), 0, "终态错误还留在待补推队列里，会永远卡住")
        self.assertEqual(self.store.dead_letter_count(), 1, "终态 payload 被静默丢弃了")

        sent_before = len(self.server.received_payloads)
        self.clock.advance(3600)
        self.collector.hour_index = 1
        self.pusher.push()
        self.assertEqual(
            len(self.server.received_payloads),
            sent_before + 1,
            "终态失败的 payload 又被重发了一次",
        )

    def test_unsupported_collector_version_is_terminal(self) -> None:
        self.server.scripted = [(200, {"error_type": UNSUPPORTED_ERROR_TYPE, "message": "太旧"})]
        self.collector.hour_index = 0
        result = self.pusher.push()

        self.assertEqual(result["error_type"], UNSUPPORTED_ERROR_TYPE)
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(self.store.dead_letter_count(), 1)

    def test_server_5xx_is_retried_on_the_next_push_instead_of_being_dropped(self) -> None:
        self.server.scripted = [(503, {"message": "upstream unavailable"})]
        self.collector.hour_index = 0
        result = self.pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(self.store.pending_count(), 1, "5xx 被当成终态，数据丢了")
        self.assertEqual(self.store.dead_letter_count(), 0)

        self.clock.advance(3600)
        self.collector.hour_index = 1
        self.pusher.push()

        self.assertEqual(
            self.observed_hours_on_server(),
            {hour_iso(0), hour_iso(1)},
            "5xx 之后那一小时没有被补推回来",
        )

    def test_network_error_backs_off_before_the_next_attempt(self) -> None:
        self.server.online = False
        self.collector.hour_index = 0
        self.pusher.push()

        self.assertEqual(self.store.pending_count(), 1)
        self.assertEqual(self.store.pending(), [], "网络错误之后没有退避，会打满重试")

        entry = self.store.pending(ignore_backoff=True)[0]
        self.assertEqual(entry.attempts, 1)
        self.assertIn("http_request_failed", entry.last_error)


class TestDiskCapAtPushTime(PusherOutboxTestCase):
    def test_full_outbox_fails_the_push_loudly_and_keeps_the_history(self) -> None:
        """磁盘上限：拒绝新增（不是丢最旧）。当次上报显式失败，历史一条不少。"""
        store = self.open_store(max_bytes=6000)
        config = self.make_config(
            outbox=OutboxConfig(enabled=True, path=str(self.db_path), max_bytes=6000)
        )
        pusher = self.make_pusher(config, store)

        self.server.online = False
        results = []
        for index in range(20):
            self.collector.hour_index = index
            results.append(pusher.push())
            self.clock.advance(3600)

        full = [r for r in results if r.get("error_type") == "outbox_full"]
        self.assertTrue(full, "磁盘上限从未触发，本条测试没有覆盖到目标行为")
        self.assertFalse(full[0]["success"])
        self.assertIn("outbox", full[0]["error_message"])

        buffered_hours = {
            fact["window_start"]
            for entry in store.pending(ignore_backoff=True)
            for fact in entry.payload.get("usage_hourly_facts", [])
        }
        self.assertIn(hour_iso(0), buffered_hours, "上限触发时最旧的一小时被丢掉了")

        self.server.online = True
        self.collector.hour_index = 99
        pusher.push()
        self.assertIn(hour_iso(0), self.observed_hours_on_server())


class TestFallbackDrain(PusherOutboxTestCase):
    """回退演练：关闭 outbox 开关前必须排空未 ACK 数据，不允许静默丢弃。"""

    def _leave_unacked_data(self) -> None:
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        self.server.online = False
        self.collector.hour_index = 0
        self.make_pusher(config, store).push()
        store.close()
        self.server.online = True

    def test_disabling_the_switch_with_unacked_data_refuses_to_push(self) -> None:
        self._leave_unacked_data()
        disabled = self.make_config(
            outbox=OutboxConfig(enabled=False, path=str(self.db_path))
        )
        self.collector.hour_index = 1
        result = DevicePusher(
            disabled,
            executor=self.collector,
            http_client=self.server,
            retry_attempts=1,
            retry_sleep=lambda _seconds: None,
        ).push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "outbox_not_drained")
        self.assertEqual(
            self.server.received_payloads,
            [],
            "关闭开关后直接直推了，未 ACK 的历史被悄悄留在磁盘上无人处理",
        )

    def test_the_unacked_data_is_still_intact_after_the_refusal(self) -> None:
        """拒绝必须是「停下」，不是「顺手清掉再直推」。"""
        self._leave_unacked_data()
        disabled = self.make_config(outbox=OutboxConfig(enabled=False, path=str(self.db_path)))
        self.collector.hour_index = 1
        DevicePusher(
            disabled,
            executor=self.collector,
            http_client=self.server,
            retry_attempts=1,
            retry_sleep=lambda _seconds: None,
        ).push()

        store = self.open_store()
        buffered = [
            fact["window_start"]
            for entry in store.pending(ignore_backoff=True)
            for fact in entry.payload.get("usage_hourly_facts", [])
        ]
        self.assertEqual(buffered, [hour_iso(0)])

    def test_after_draining_the_disabled_switch_falls_back_to_direct_push(self) -> None:
        """排空之后回退路径必须真的可用，否则回退开关等于摆设。"""
        self._leave_unacked_data()

        # 排空：先把积压推完（等价于运维执行的「排空」动作）。
        enabled = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        drain_store = self.open_store()
        self.clock.advance(3600)
        self.collector.hour_index = 1
        self.make_pusher(enabled, drain_store).push()
        drain_store.assert_drained()
        drain_store.close()

        disabled = self.make_config(outbox=OutboxConfig(enabled=False, path=str(self.db_path)))
        self.collector.hour_index = 2
        result = DevicePusher(
            disabled,
            executor=self.collector,
            http_client=self.server,
            retry_attempts=1,
            retry_sleep=lambda _seconds: None,
        ).push()

        self.assertTrue(result["success"], result)
        self.assertIn(hour_iso(2), self.observed_hours_on_server())

    def test_exported_data_also_counts_as_drained(self) -> None:
        """服务端长期不可用时，导出 + 显式丢弃是第二条合法排空路径。"""
        self._leave_unacked_data()
        store = self.open_store()
        dest = self.root / "outbox-export.json"
        store.export_undelivered(dest)
        store.discard_undelivered(exported_to=dest)
        store.close()

        exported = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(len(exported), 1)

        disabled = self.make_config(outbox=OutboxConfig(enabled=False, path=str(self.db_path)))
        self.collector.hour_index = 2
        result = DevicePusher(
            disabled,
            executor=self.collector,
            http_client=self.server,
            retry_attempts=1,
            retry_sleep=lambda _seconds: None,
        ).push()
        self.assertTrue(result["success"], result)


class TestOutboxItselfFailing(PusherOutboxTestCase):
    """outbox 是新引入的故障源，它自己坏掉时不许把整次采集变成一个栈回溯。"""

    def test_sqlite_failure_returns_a_structured_result_instead_of_raising(self) -> None:
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)
        self.collector.hour_index = 0

        with patch.object(
            CollectorStore, "enqueue", side_effect=sqlite3.OperationalError("database is locked")
        ):
            result = pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "outbox_unavailable")
        self.assertIn("database is locked", result["error_message"])

    def test_a_broken_outbox_does_not_silently_fall_back_to_direct_push(self) -> None:
        """静默直推比报错更糟：数据看似送出去了，磁盘上的积压却再也没人管。"""
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)
        self.collector.hour_index = 0

        with patch.object(
            CollectorStore, "enqueue", side_effect=sqlite3.OperationalError("database is locked")
        ):
            pusher.push()

        self.assertEqual(self.server.received_payloads, [])


class TestSourceStatusHeartbeatDoesNotFloodTheOutbox(PusherOutboxTestCase):
    """采集失败的状态心跳是「当前状态」，不是不可再生的历史。

    「采集坏了 + 网也断了」会同时发生（比如换了机器、装漏了 ccusage）。这时每一轮
    都会产生一条 `usage_daily: []` 的失败心跳。如果它们和用量事实一样被无限缓冲，
    磁盘上限会被这些**可再生的**心跳吃光，之后真正不可再生的用量 payload 反而被
    `outbox_full` 拒之门外——防丢数的机制亲手造成了丢数。
    """

    class BrokenCollector:
        def __call__(self, argv: list[str], timeout: float) -> CommandResult:
            return CommandResult(
                exit_code=None,
                error_type="missing_tool",
                error_message="[Errno 2] No such file or directory: 'ccusage'",
            )

    def test_repeated_failure_heartbeats_collapse_to_the_latest_one(self) -> None:
        self.collector = self.BrokenCollector()
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)

        self.server.online = False
        for _ in range(20):
            pusher.push()
            self.clock.advance(3600)

        self.assertEqual(
            store.pending_count(),
            1,
            "20 轮失败心跳攒了 20 条，磁盘上限会被可再生的状态心跳吃光",
        )

    def test_the_latest_heartbeat_still_reaches_the_server_after_recovery(self) -> None:
        """收敛不等于丢弃：最新一条状态必须还是会送到。"""
        self.collector = self.BrokenCollector()
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)

        self.server.online = False
        pusher.push()
        self.clock.advance(3600)
        self.server.online = True
        pusher.push()

        statuses = [p["collection_status"] for p in self.server.received_payloads]
        self.assertIn("missing_tool", statuses)
        self.assertEqual(store.pending_count(), 0)

    def test_usage_payloads_are_never_collapsed_that_way(self) -> None:
        """反向：真正的用量事实绝不能被同一个机制折叠掉。"""
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        pusher = self.make_pusher(config, store)
        self.server.online = False
        for index in range(5):
            self.collector.hour_index = index
            pusher.push()
            self.clock.advance(3600)
        self.assertEqual(store.pending_count(), 5)


class TestKindIsolation(PusherOutboxTestCase):
    """用量补推绝不能把排队中的额度观测打到 `/ingest`。

    两者共用同一个 outbox 库（设备配置里同一个 `outbox` 块），但走两个不同的
    ingest 端点。#87 把额度观测接进这个库之后，用量侧的补推如果不按 kind 过滤，
    就会把额度 payload POST 到 `/ingest`，服务端拒收 → 判成终态 → 进死信，
    一条本来能补推成功的观测就此消失。
    """

    def test_usage_flush_leaves_queued_limit_observations_alone(self) -> None:
        outbox = OutboxConfig(enabled=True, path=str(self.db_path))
        store = self.open_store()
        store.enqueue(
            {"schema_version": 1, "observed_at": "2026-06-03T11:00:00+08:00", "windows": [{"provider": "codex"}]},
            kind=KIND_LIMITS,
            dedupe_key="limits:codex",
            ttl_seconds=3600.0,
        )
        result = self.make_pusher(self.make_config(outbox=outbox), store).push()

        self.assertTrue(result.get("success"), result)
        self.assertGreater(len(self.server.received_payloads), 0, "这一轮必须真的推了用量事实")
        for payload in self.server.received_payloads:
            self.assertNotIn("windows", payload, "额度观测被用量补推打到了 /ingest")
        self.assertEqual(store.dead_letter_count(), 0, "额度观测被打进了死信表")
        self.assertEqual(
            [entry.kind for entry in store.pending(ignore_backoff=True)],
            [KIND_LIMITS],
            "额度观测必须原封不动留在队列里，等 push-limits 补推",
        )


class TestPayloadIsUnchangedByTheOutbox(PusherOutboxTestCase):
    """payload 语义与字段零变化——outbox 只是一个缓冲，不是一层翻译。"""

    VOLATILE = ("observed_at",)

    def _push_and_capture(self, store: CollectorStore | None, config: DeviceConfig) -> dict:
        self.collector.hour_index = 0
        self.make_pusher(config, store).push()
        payload = dict(self.server.received_payloads[-1])
        for field in self.VOLATILE:
            payload.pop(field, None)
        return payload

    def test_the_payload_sent_through_the_outbox_equals_the_directly_pushed_one(self) -> None:
        direct = self._push_and_capture(None, self.make_config(outbox=None))

        self.server.facts.clear()
        self.server.received_payloads.clear()
        self.collector = ScriptedCollector()
        buffered = self._push_and_capture(
            self.open_store(),
            self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path))),
        )

        self.assertEqual(buffered, direct)

    def test_a_buffered_payload_keeps_none_valued_fields(self) -> None:
        """JSON 往返最容易悄悄吃掉的就是显式 None，而它在归属块里是有含义的。"""
        store = self.open_store()
        config = self.make_config(outbox=OutboxConfig(enabled=True, path=str(self.db_path)))
        self.server.online = False
        self.collector.hour_index = 0
        self.make_pusher(config, store).push()

        entry = store.pending(ignore_backoff=True)[0]
        account = entry.payload["usage_hourly_facts"][0]["ai_account"]
        self.assertIn("display_name", account)
        self.assertIsNone(account["display_name"])


if __name__ == "__main__":
    unittest.main()
