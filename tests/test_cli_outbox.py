"""outbox 的运维入口：看状态、导出、排空（Issue #87）。

#73 把「回退前必须排空、不允许静默丢弃」实现了也测了，但运维真要执行时**只能手写
Python 调内部 API**。一个只能靠写代码触发的回退路径，在真出事那天等于没有。

本文件守的是这三条命令的用户结果：

- `outbox-status`：能看出现在还剩多少未投递，以及下一步该做什么；
- `outbox-export`：拿到可恢复的副本，且**导出不删除任何东西**；
- `outbox-drain`：导出之后才允许清空，且必须显式确认——没有「无条件清空」的入口。
"""

from __future__ import annotations

import io
import json
import os
import unittest
import unittest.mock
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_usage_widget import cli
from ai_usage_widget.collector_store import KIND_LIMITS, CollectorStore, OutboxConfig


class CliOutboxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.outbox_path = self.root / "outbox.sqlite"
        self.config_path = self.root / "device.json"
        self._write_config(enabled=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_config(self, *, enabled: bool, with_outbox: bool = True) -> None:
        data = {
            "schema_version": 1,
            "source_id": "linux-dev-bob",
            "host": "linux-dev",
            "machine": "linux-dev",
            "os_user": "bob",
            "platform": "linux",
            "timezone": "Asia/Shanghai",
            "server_url": "https://example.test/ingest",
        }
        if with_outbox:
            data["outbox"] = {"enabled": enabled, "path": str(self.outbox_path)}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")

    def _seed(self, *, pending: int = 0, dead: int = 0) -> None:
        config = OutboxConfig(enabled=True, path=str(self.outbox_path))
        with CollectorStore.from_config(config) as store:
            for index in range(pending):
                store.enqueue({"marker": f"usage-{index}"})
            for index in range(dead):
                entry_id = store.enqueue(
                    {"marker": f"limits-{index}"}, kind=KIND_LIMITS, dedupe_key=f"slot-{index}", ttl_seconds=3600
                )
                store.dead_letter(entry_id, reason="http_schema_invalid: bad payload")

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _undelivered(self) -> int:
        config = OutboxConfig(enabled=True, path=str(self.outbox_path))
        with CollectorStore.from_config(config) as store:
            return store.undelivered_count()


class TestOutboxStatus(CliOutboxTestCase):
    def test_status_reports_how_much_is_still_undelivered(self) -> None:
        self._seed(pending=3, dead=2)
        code, out, _ = self._run(["outbox-status", "--config", str(self.config_path)])
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["undelivered"], 5, "运维要能一眼看出还剩多少没投出去")
        self.assertEqual(payload["pending"], 3)
        self.assertEqual(payload["dead_letters"], 2)
        self.assertEqual(payload["path"], str(self.outbox_path))
        self.assertTrue(payload["exists"])
        self.assertIn("outbox-export", payload["next_step"], "有积压时要直接给出下一步命令")

    def test_status_on_a_clean_store_says_so(self) -> None:
        self._seed()
        code, out, _ = self._run(["outbox-status", "--config", str(self.config_path)])
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["undelivered"], 0)
        self.assertTrue(payload["drained"], "空库必须明确说「已排空」，而不是让人自己看数字")

    def test_status_without_a_store_file_is_not_an_error(self) -> None:
        """还没攒下任何东西时库文件根本不存在，这不是故障。"""
        code, out, _ = self._run(["outbox-status", "--config", str(self.config_path)])
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["undelivered"], 0)
        self.assertTrue(payload["drained"])
        self.assertFalse(self.outbox_path.exists(), "只是看状态，不该顺手把库建出来")

    def test_status_without_an_outbox_block_fails_loudly(self) -> None:
        """从未启用过 outbox 的设备：明确报错，而不是打印一份「0 条」误导人。"""
        self._write_config(enabled=True, with_outbox=False)
        code, _, err = self._run(["outbox-status", "--config", str(self.config_path)])

        self.assertEqual(code, 1)
        self.assertIn("outbox", err)


class TestOutboxExport(CliOutboxTestCase):
    def test_export_writes_every_undelivered_record_and_deletes_nothing(self) -> None:
        self._seed(pending=2, dead=1)
        dest = self.root / "export.json"

        code, out, _ = self._run(
            ["outbox-export", "--config", str(self.config_path), "--dest", str(dest)]
        )
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["exported"], 3)
        records = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 3)
        self.assertEqual(
            {record["state"] for record in records}, {"pending", "dead_letter"},
            "导出必须同时覆盖待补推与死信，只导一半等于静默丢另一半",
        )
        self.assertEqual(self._undelivered(), 3, "导出即丢弃是另一种静默丢失")

    def test_export_on_a_clean_store_writes_an_empty_list(self) -> None:
        self._seed()
        dest = self.root / "export.json"
        code, out, _ = self._run(
            ["outbox-export", "--config", str(self.config_path), "--dest", str(dest)]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["exported"], 0)
        self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), [])


class TestOutboxDrain(CliOutboxTestCase):
    def test_drain_refuses_without_explicit_confirmation(self) -> None:
        """没有「无条件清空」的入口：那等于给静默丢弃开一扇门。"""
        self._seed(pending=2)
        dest = self.root / "export.json"

        code, _, err = self._run(
            ["outbox-drain", "--config", str(self.config_path), "--export-to", str(dest)]
        )

        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertEqual(self._undelivered(), 2, "没确认就把数据清了，正是这条命令要防的事")

    def test_drain_exports_first_then_clears(self) -> None:
        self._seed(pending=2, dead=1)
        dest = self.root / "export.json"

        code, out, _ = self._run(
            ["outbox-drain", "--config", str(self.config_path), "--export-to", str(dest), "--yes"]
        )
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["exported"], 3)
        self.assertEqual(payload["discarded"], 3)
        self.assertEqual(len(json.loads(dest.read_text(encoding="utf-8"))), 3, "副本必须先落盘再清空")
        self.assertEqual(self._undelivered(), 0)

    def test_drain_unblocks_the_fallback_to_direct_push(self) -> None:
        """排空的**用户结果**是：关掉 outbox 之后 push 不再被拦。

        只断言「表清空了」是不够的——真正要证明的是回退演练能走通。
        """
        self._seed(pending=1)
        dest = self.root / "export.json"
        self._run(["outbox-drain", "--config", str(self.config_path), "--export-to", str(dest), "--yes"])

        config = OutboxConfig(enabled=True, path=str(self.outbox_path))
        with CollectorStore.from_config(config) as store:
            store.assert_drained()  # 未排空会抛 OutboxNotDrained

    def test_drain_on_a_clean_store_is_a_no_op(self) -> None:
        self._seed()
        dest = self.root / "export.json"
        code, out, _ = self._run(
            ["outbox-drain", "--config", str(self.config_path), "--export-to", str(dest), "--yes"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["discarded"], 0)


class TestPushLimitsWiring(CliOutboxTestCase):
    """`push-limits` 只有在给了设备配置时才走 outbox；不给就是原来的直推。"""

    def setUp(self) -> None:
        super().setUp()
        # fixture 里的观测时刻是固定的；不把「现在」钉住，provider 会因为观测过期被判
        # unavailable，测出来的就不是投递路径而是采集降级。
        self._now = unittest.mock.patch(
            "ai_usage_widget.limits_runtime._default_now",
            return_value="2026-06-03T10:02:00+08:00",
        )
        self._now.start()
        self.addCleanup(self._now.stop)

    def test_push_limits_without_config_keeps_direct_push(self) -> None:
        calls: list[dict] = []

        def fake_push_limits(url, token, payload, timeout=10.0):
            calls.append(payload)
            return {"success": True, "windows_written": len(payload["windows"])}

        fixtures = Path(__file__).resolve().parent / "fixtures"
        with unittest.mock.patch.object(cli, "push_limits_payload", fake_push_limits), \
                unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_PUSH_TOKEN": "secret"}):
            code, out, _ = self._run([
                "push-limits",
                "--provider-fixture", str(fixtures / "limits_runtime_fixture.json"),
                "--url", "https://example.test/ingest-limits",
                "--token-env", "AI_USAGE_TEST_PUSH_TOKEN",
            ])

        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.outbox_path.exists(), "没给设备配置就不该建 outbox 库")

    def test_push_limits_with_config_buffers_when_offline(self) -> None:
        fixtures = Path(__file__).resolve().parent / "fixtures"

        def offline_transport(url, token, payload, timeout):
            raise OSError("network unreachable")

        with unittest.mock.patch.object(cli, "post_limits_payload", offline_transport), \
                unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_PUSH_TOKEN": "secret"}):
            code, out, _ = self._run([
                "push-limits",
                "--provider-fixture", str(fixtures / "limits_runtime_fixture.json"),
                "--url", "https://example.test/ingest-limits",
                "--token-env", "AI_USAGE_TEST_PUSH_TOKEN",
                "--config", str(self.config_path),
            ])

        payload = json.loads(out)
        self.assertFalse(payload["push"]["delivered"], "断网时不许报成已送达")
        self.assertTrue(payload["push"]["queued"])
        self.assertEqual(self._undelivered(), 1, "断网的额度观测必须留在本地")
        self.assertEqual(code, 0, "数据安全落盘不算命令失败，否则调度器会一直报错")


    def test_push_limits_fails_when_the_observation_is_neither_delivered_nor_kept(self) -> None:
        """终态拒收 = 数据真的没了，必须 exit 1。

        「落盘等补推」退 0 是刻意的（断网是常态，让调度器每次断网都报错，
        真故障就淹没在噪音里）。但这条豁免只对**还留在本地**的观测成立——
        终态错误进死信之后没人会再补推它，把它也报成 0 就是静默失败。
        """
        fixtures = Path(__file__).resolve().parent / "fixtures"

        def rejecting_transport(url, token, payload, timeout):
            return 400, {"error_type": "http_schema_invalid", "message": "windows required"}

        with unittest.mock.patch.object(cli, "post_limits_payload", rejecting_transport), \
                unittest.mock.patch.dict(os.environ, {"AI_USAGE_TEST_PUSH_TOKEN": "secret"}):
            code, out, _ = self._run([
                "push-limits",
                "--provider-fixture", str(fixtures / "limits_runtime_fixture.json"),
                "--url", "https://example.test/ingest-limits",
                "--token-env", "AI_USAGE_TEST_PUSH_TOKEN",
                "--config", str(self.config_path),
            ])

        payload = json.loads(out)
        self.assertFalse(payload["push"]["delivered"])
        self.assertFalse(payload["push"]["queued"], "终态拒收之后这份观测已经不在待补推队列里")
        self.assertEqual(code, 1, "没送达也没留在本地，必须是失败")
        self.assertEqual(self._undelivered(), 1, "终态留档不等于消失：死信表里要看得见")


if __name__ == "__main__":
    unittest.main()
