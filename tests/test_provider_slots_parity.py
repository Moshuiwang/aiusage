"""Issue #61 验收 6：Python 读模型与 Cloudflare Native Worker 在同一 fixture 下产出一致的 provider_slots。

同一份 SQL fixture 有两个消费方：

- 本文件：用 Python 读模型（snapshot_builder + mobile_summary）重放，比对 golden。
- ``cloudflare/native-worker/test/provider-slots-parity.test.ts``：用 Native Worker
  在 Miniflare D1 上重放同一份 fixture，比对同一个 golden。

golden 里的值最初是按验收标准逐条手写的，不是从任一侧实现导出的；两侧都必须匹配它。
重新生成是**独立动作**，走 ``python3 scripts/gen_provider_slots_golden.py``，不在测试里做，
免得测试变红时被顺手用掉。生成后必须逐条复核 diff：改 golden 等于改验收预期。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ai_usage_widget.mobile_summary import build_mobile_summary
from ai_usage_widget.snapshot_builder import build_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
SCENARIO_DIR = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "provider_slots"
GOLDEN_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "provider_slots_golden.json"

TIMEZONE = "Asia/Shanghai"
FIXED_NOW = "2026-06-03T12:00:00+08:00"
DATE = "2026-06-03"
PERIOD = "today"
ENDPOINTS = (
    ("summary", "/api/summary?date=2026-06-03&period=today"),
    ("mobile-summary", "/api/mobile/summary?date=2026-06-03&period=today"),
)


class TestProviderSlotsCrossImplementationContract(unittest.TestCase):
    maxDiff = None

    def test_python_read_model_matches_provider_slots_golden(self) -> None:
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(_collect_records(), expected)

    def test_every_scenario_keeps_usage_accounting_consistent_with_summary(self) -> None:
        """槽位与 summary 不能互相矛盾：归属 + 未归属必须等于该周期的总量。"""
        for record in json.loads(GOLDEN_PATH.read_text(encoding="utf-8")):
            with self.subTest(record=record["name"]):
                coverage = record["provider_usage_coverage"]
                self.assertEqual(
                    coverage["attributed_tokens"] + coverage["unattributed_tokens"],
                    coverage["total_tokens"],
                )
                self.assertEqual(
                    coverage["status"],
                    "complete" if coverage["unattributed_tokens"] == 0 else "partial",
                )
                slot_tokens = sum(row["usage"]["total_tokens"] for row in record["provider_slots"])
                self.assertLessEqual(slot_tokens, coverage["attributed_tokens"])

    def test_aggregate_agent_usage_lands_in_the_canonical_provider_slot(self) -> None:
        """agent='all' 但 ai_provider='claude' 时，用量必须进 Claude 槽位（11 号 fixture 锁死）。"""
        golden = {record["name"]: record for record in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))}

        for endpoint in ("summary", "mobile-summary"):
            record = golden[f"11-aggregate-agent-with-canonical-provider:{endpoint}"]
            claude = next(row for row in record["provider_slots"] if row["provider"] == "claude")
            self.assertEqual(claude["usage"]["status"], "available")
            self.assertEqual(claude["usage"]["total_tokens"], 3100)
            self.assertEqual(record["provider_usage_coverage"]["unattributed_tokens"], 0)

    def test_golden_covers_all_four_usage_and_quota_combinations(self) -> None:
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        combinations = set()
        for record in golden:
            claude = next(row for row in record["provider_slots"] if row["provider"] == "claude")
            combinations.add((claude["usage"]["status"], claude["quota"]["status"]))

        self.assertEqual(
            combinations,
            {
                ("available", "available"),
                ("available", "missing"),
                ("missing", "available"),
                ("missing", "missing"),
            },
        )

    def test_golden_missing_quota_never_carries_percentages_or_reset(self) -> None:
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        checked = 0
        for record in golden:
            for slot in record["provider_slots"]:
                quota = slot["quota"]
                if quota["status"] != "missing":
                    continue
                checked += 1
                self.assertEqual(quota["windows"], [])
                self.assertIn("last_verified_at", quota)
                serialized = json.dumps(quota, sort_keys=True)
                for leaked in ("used_percent", "remaining_percent", "reset_at"):
                    self.assertNotIn(leaked, serialized, f"{record['name']} / {slot['provider']}")
        self.assertGreater(checked, 0)

    def test_scenario_fixtures_are_offline_sql_replays(self) -> None:
        scenarios = sorted(path.name for path in SCENARIO_DIR.glob("*.sql"))
        self.assertEqual(
            scenarios,
            [
                "01-usage-and-quota.sql",
                "02-usage-without-quota.sql",
                "03-quota-without-usage.sql",
                "04-neither.sql",
                "05-codex-quota-only.sql",
                "06-expired-official-quota.sql",
                "07-provider-failed-after-success.sql",
                "08-stale-official-with-local-estimate.sql",
                "09-local-estimate-only.sql",
                "10-estimated-observation-newer-than-official.sql",
                "11-aggregate-agent-with-canonical-provider.sql",
                "12-naive-limit-timestamps.sql",
            ],
        )

    def test_golden_covers_every_quota_missing_reason(self) -> None:
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        reasons = {
            slot["quota"]["reason"]
            for record in golden
            for slot in record["provider_slots"]
            if slot["quota"]["status"] == "missing"
        }

        self.assertEqual(reasons, {"no_data", "unverified", "stale", "expired", "unavailable"})

    def test_golden_never_borrows_local_estimate_freshness_for_official_quota(self) -> None:
        """本地估算的新鲜度不得冒充官方验证时间（08 / 09 两个 fixture 锁死）。"""
        golden = {record["name"]: record for record in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))}

        for endpoint in ("summary", "mobile-summary"):
            stale = _claude_quota(golden[f"08-stale-official-with-local-estimate:{endpoint}"])
            self.assertEqual(stale["last_verified_at"], "2026-06-01T09:00:00+08:00")
            self.assertEqual(stale["source_type"], "oauth_usage_api")

            estimate_only = _claude_quota(golden[f"09-local-estimate-only:{endpoint}"])
            self.assertEqual(estimate_only["reason"], "unverified")
            self.assertIsNone(estimate_only["last_verified_at"])


def _claude_quota(record: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in record["provider_slots"] if row["provider"] == "claude")["quota"]


def _collect_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for scenario_path in sorted(SCENARIO_DIR.glob("*.sql")):
        scenario = scenario_path.stem
        snapshot = _build_snapshot_for(scenario_path)
        mobile = build_mobile_summary(snapshot)
        payloads = {"summary": snapshot, "mobile-summary": mobile}
        for endpoint, path in ENDPOINTS:
            records.append({
                "name": f"{scenario}:{endpoint}",
                "scenario": scenario,
                "request": {"method": "GET", "path": path, "auth": True},
                "provider_slots": payloads[endpoint]["provider_slots"],
                "provider_usage_coverage": payloads[endpoint]["provider_usage_coverage"],
            })
    return records


def _build_snapshot_for(scenario_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "provider-slots.sqlite"
        output_path = Path(temp_dir) / "snapshot.json"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.executescript(scenario_path.read_text(encoding="utf-8"))
        build_snapshot(
            db_path=str(db_path),
            output_path=str(output_path),
            date_str=DATE,
            timezone_str=TIMEZONE,
            current_time_str=FIXED_NOW,
            period=PERIOD,
        )
        return json.loads(output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
