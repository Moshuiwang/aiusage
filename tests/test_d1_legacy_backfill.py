from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.d1_legacy_backfill import (
    BackfillOptions,
    apply_plan,
    build_plan,
    emit_sql,
    render_report,
    summarize_d1_meta,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"


class D1LegacyBackfillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "export.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA.read_text())
        self._seed()

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_plan_uses_only_missing_legacy_keys_and_preserves_identity(self) -> None:
        changes_before = self.conn.total_changes
        plan = build_plan(self.conn, self.options())

        self.assertEqual(self.conn.total_changes, changes_before)
        self.assertEqual(len(plan.daily_rows), 2)
        self.assertEqual(len(plan.hourly_rows), 1)
        daily = next(row for row in plan.daily_rows if row["source_id"] == "mac-a")
        self.assertEqual(daily["machine_id"], "macbook")
        self.assertEqual(daily["os_user"], "alice")
        self.assertEqual(daily["ai_account_id"], "claude-main")
        self.assertEqual(daily["provenance"], "historical_ccusage_fallback_v1")
        self.assertFalse(plan.legacy_writes)
        self.assertEqual(plan.model_rows, [])
        self.assertEqual(plan.unresolved_identities, [])

        # A legacy row that already has a detailed ledger day is not copied.
        self.assertNotIn(
            ("mac-a", "2026-05-20", "claude"),
            {(row["source_id"], row["date"], row["agent"]) for row in plan.daily_rows},
        )

    def test_apply_is_idempotent_and_never_writes_archived_tables_or_models(self) -> None:
        plan = build_plan(self.conn, self.options())
        archived_before = self._archived_snapshot()

        first = apply_plan(self.conn, plan)
        second = apply_plan(self.conn, plan)

        self.assertGreater(first.rows_written, 0)
        self.assertEqual(second.rows_written, 0)
        self.assertEqual(self._archived_snapshot(), archived_before)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM usage_hourly_models").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM usage_daily_rollups "
                "WHERE provenance='historical_ccusage_fallback_v1'"
            ).fetchone()[0],
            2,
        )

    def test_batches_resume_after_partial_execution(self) -> None:
        plan = build_plan(self.conn, self.options(batch_size=1))
        self.assertGreaterEqual(len(plan.batches), 3)
        for batch in plan.batches:
            tables = [sql.split(" ", 3)[2] for sql, _ in batch]
            if "usage_hourly_facts" in tables:
                self.assertIn("usage_hourly_rollups", tables)

        apply_plan(self.conn, plan, batch_indexes=[0])
        partial_count = self.conn.execute(
            "SELECT COUNT(*) FROM usage_daily_rollups "
            "WHERE provenance='historical_ccusage_fallback_v1'"
        ).fetchone()[0]
        self.assertLess(partial_count, len(plan.daily_rows))

        apply_plan(self.conn, plan)
        resumed_count = self.conn.execute(
            "SELECT COUNT(*) FROM usage_daily_rollups "
            "WHERE provenance='historical_ccusage_fallback_v1'"
        ).fetchone()[0]
        self.assertEqual(resumed_count, len(plan.daily_rows))
        self.assertEqual(apply_plan(self.conn, plan).rows_written, 0)

    def test_report_covers_periods_daily_filters_counts_and_estimates(self) -> None:
        plan = build_plan(self.conn, self.options())
        before = render_report(self.conn, plan)
        apply_plan(self.conn, plan)
        after = render_report(self.conn, plan)

        self.assertEqual(before["parity"]["all"]["difference_tokens"], -360)
        self.assertEqual(after["parity"]["all"]["difference_tokens"], 0)
        self.assertEqual(after["parity"]["month"]["difference_tokens"], 0)
        self.assertEqual(after["parity"]["week"]["difference_tokens"], 0)
        self.assertEqual(after["parity"]["today"]["difference_tokens"], 0)
        self.assertEqual(after["daily_differences"], [])
        self.assertEqual(after["filters"]["machines"]["macbook"]["difference_tokens"], 0)
        self.assertEqual(after["filters"]["system_accounts"]["alice"]["difference_tokens"], 0)
        self.assertEqual(after["filters"]["ai_accounts"]["claude-main"]["difference_tokens"], 0)
        self.assertGreater(before["estimated_d1"]["rows_read"], 0)
        self.assertGreater(before["estimated_d1"]["rows_written"], 0)
        self.assertIn("usage_daily", after["table_counts"]["legacy"])
        self.assertIn("usage_daily_rollups", after["table_counts"]["ledger"])

    def test_missing_or_ambiguous_account_mapping_stops_plan(self) -> None:
        self.conn.execute(
            """
            INSERT INTO usage_hourly_facts (
              fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
              agent, client, window_start, window_end, timezone, total_tokens,
              attribution_confidence, provenance, first_seen_at, last_seen_at
            ) VALUES (
              'ambiguous', 'mac-a', 'macbook', 'alice', 'claude', 'claude-other',
              'claude', 'cli', '2026-07-01T10:00:00+08:00',
              '2026-07-01T11:00:00+08:00', 'Asia/Shanghai', 1,
              'observed', 'fixture', '2026-07-01T10:00:00+08:00',
              '2026-07-01T10:00:00+08:00'
            )
            """
        )
        self.conn.commit()

        plan = build_plan(self.conn, self.options())

        self.assertTrue(plan.unresolved_identities)
        self.assertEqual(plan.daily_rows, [])
        self.assertIn("multiple accounts", plan.unresolved_identities[0]["reason"])

    def test_multiple_machine_history_requires_explicit_review(self) -> None:
        self.conn.execute(
            """
            INSERT INTO usage_hourly_facts (
              fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
              agent, client, window_start, window_end, timezone, total_tokens,
              attribution_confidence, provenance, first_seen_at, last_seen_at
            ) VALUES (
              'other-machine', 'linux-b', 'retired-linuxbox', 'bob',
              'codex', 'codex-main', 'codex', 'cli',
              '2026-07-01T11:00:00+08:00', '2026-07-01T12:00:00+08:00',
              'Asia/Shanghai', 1, 'observed', 'fixture',
              '2026-07-01T11:00:00+08:00', '2026-07-01T11:00:00+08:00'
            )
            """
        )
        self.conn.commit()

        plan = build_plan(self.conn, self.options())

        self.assertEqual(plan.daily_rows, [])
        self.assertTrue(any(
            item["source_id"] == "linux-b" and "multiple machines" in item["reason"]
            for item in plan.unresolved_identities
        ))

    def test_all_agent_overlap_stops_instead_of_reassigning_detailed_accounts(self) -> None:
        self.conn.execute(
            """
            INSERT INTO usage_daily (
              source_id, date, agent, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
              metadata_json, raw_json, first_seen_at, last_seen_at
            ) VALUES (
              'mac-a', '2026-05-20', 'all', 220, 50, 30, 0, 300, 3.0,
              '{}', '{}', 'x', 'x'
            )
            """
        )
        self.conn.commit()
        options = BackfillOptions(
            start_date="2026-05-18",
            end_date="2026-07-01",
            as_of_date="2026-07-01",
            identity_overrides={
                "mac-a|all": {
                    "machine_id": "macbook",
                    "os_user": "alice",
                    "ai_provider": "claude",
                    "ai_account_id": "claude-main",
                }
            },
        )

        plan = build_plan(self.conn, options)
        report = render_report(self.conn, plan)

        self.assertEqual(plan.daily_rows, [])
        self.assertTrue(any(
            item["source_id"] == "mac-a" and "overlaps detailed identities" in item["reason"]
            for item in plan.unresolved_identities
        ))
        self.assertEqual(report["status"], "blocked_identity_mapping")
        self.assertTrue(any(
            item["source_id"] == "mac-a" and "overlaps detailed identities" in item["reason"]
            for item in report["unresolved_identities"]
        ))

    def test_all_agent_dry_run_renders_structured_report(self) -> None:
        self.conn.execute(
            """
            INSERT INTO usage_daily (
              source_id, date, agent, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
              metadata_json, raw_json, first_seen_at, last_seen_at
            ) VALUES (
              'mac-a', '2026-05-21', 'all', 220, 50, 30, 0, 300, 3.0,
              '{}', '{}', 'x', 'x'
            )
            """
        )
        self.conn.commit()
        options = BackfillOptions(
            start_date="2026-05-18",
            end_date="2026-07-01",
            as_of_date="2026-07-01",
            identity_overrides={
                "mac-a|all": {
                    "machine_id": "macbook",
                    "os_user": "alice",
                    "ai_provider": "claude",
                    "ai_account_id": "claude-main",
                }
            },
        )

        plan = build_plan(self.conn, options)
        report = render_report(self.conn, plan)

        self.assertEqual(plan.unresolved_identities, [])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["unresolved_identities"], [])
        self.assertEqual(report["plan"]["model_rows"], 0)

    def test_emitted_sql_is_bounded_new_table_only_and_has_targeted_rollback(self) -> None:
        plan = build_plan(self.conn, self.options(batch_size=1))
        output = Path(self.tempdir.name) / "sql"

        paths = emit_sql(plan, output)

        apply_files = [path for path in paths if path.name.startswith("apply-")]
        self.assertTrue(apply_files)
        for path in apply_files:
            sql = path.read_text()
            self.assertLessEqual(sql.count("INSERT INTO"), 2)
            self.assertNotIn("INSERT INTO usage_daily ", sql)
            self.assertNotIn("UPDATE usage_daily ", sql)
            self.assertNotIn("DELETE FROM usage_daily ", sql)
            self.assertNotIn("usage_daily_models", sql)
            self.assertNotIn("usage_blocks", sql)
            self.conn.executescript(sql)
        self.assertEqual(render_report(self.conn, plan)["daily_differences"], [])
        rollback = (output / "rollback.sql").read_text()
        self.assertIn("historical_ccusage_fallback_v1", rollback)
        self.assertIn("legacy_hourly_archive_backfill_v1", rollback)
        self.assertNotIn("DELETE FROM usage_daily;", rollback)
        self.assertIn("fact_id = 'legacy-hourly-v1-", rollback)
        self.conn.executescript(rollback)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM usage_daily_rollups "
                "WHERE provenance='historical_ccusage_fallback_v1'"
            ).fetchone()[0],
            0,
        )

    def test_actual_d1_meta_is_aggregated_across_batches(self) -> None:
        actual = summarize_d1_meta([
            [{"results": [], "meta": {"rows_read": 10, "rows_written": 3}}],
            {"result": [{"meta": {"rows_read": 7, "rows_written": 2}}]},
        ])

        self.assertEqual(actual, {"rows_read": 17, "rows_written": 5})

    def options(self, *, batch_size: int = 500) -> BackfillOptions:
        return BackfillOptions(
            start_date="2026-05-18",
            end_date="2026-07-01",
            as_of_date="2026-07-01",
            timezone="Asia/Shanghai",
            batch_size=batch_size,
        )

    def _archived_snapshot(self) -> dict[str, list[tuple[object, ...]]]:
        result: dict[str, list[tuple[object, ...]]] = {}
        for table in ("usage_daily", "usage_daily_models", "usage_hourly", "usage_blocks"):
            result[table] = [
                tuple(row)
                for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
            ]
        return result

    def _seed(self) -> None:
        self.conn.executescript(
            """
            INSERT INTO source_identities (
              source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
            ) VALUES
              ('mac-a', 'macbook', 'macbook', 'alice', 'darwin', '2026-05-01', '2026-07-01'),
              ('linux-b', 'linuxbox', 'linuxbox', 'bob', 'linux', '2026-05-01', '2026-07-01');

            INSERT INTO machines (
              machine_id, machine_name, host, platform, first_seen_at, last_seen_at
            ) VALUES
              ('macbook', 'macbook', 'macbook', 'darwin', '2026-05-01', '2026-07-01'),
              ('linuxbox', 'linuxbox', 'linuxbox', 'linux', '2026-05-01', '2026-07-01');

            INSERT INTO ai_accounts (
              provider, account_id, account_label, first_seen_at, last_seen_at
            ) VALUES
              ('claude', 'claude-main', 'Claude Main', '2026-05-01', '2026-07-01'),
              ('codex', 'codex-main', 'Codex Main', '2026-05-01', '2026-07-01');

            INSERT INTO usage_daily (
              source_id, date, agent, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
              metadata_json, raw_json, first_seen_at, last_seen_at
            ) VALUES
              ('mac-a', '2026-05-19', 'claude', 100, 20, 10, 0, 130, 1.0, '{}', '{}', 'x', 'x'),
              ('mac-a', '2026-05-20', 'claude', 150, 30, 20, 0, 200, 2.0, '{}', '{}', 'x', 'x'),
              ('linux-b', '2026-06-30', 'codex', 200, 20, 10, 0, 230, 3.0, '{}', '{}', 'x', 'x');

            INSERT INTO usage_hourly (
              source_id, hour, agent, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
              metadata_json, raw_json, first_seen_at, last_seen_at
            ) VALUES
              ('mac-a', '2026-05-19T09:00:00+08:00', 'claude',
               100, 20, 10, 0, 130, 1.0, '{}', '{}', 'x', 'x');

            INSERT INTO usage_hourly_facts (
              fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
              agent, client, window_start, window_end, timezone, input_tokens,
              output_tokens, cache_creation_tokens, cache_read_tokens,
              reasoning_output_tokens, total_tokens, total_cost, event_count,
              session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
            ) VALUES
              ('existing-mac', 'mac-a', 'macbook', 'alice', 'claude', 'claude-main',
               'claude', 'cli', '2026-05-20T09:00:00+08:00',
               '2026-05-20T10:00:00+08:00', 'Asia/Shanghai', 150, 30, 20, 0,
               0, 200, 2.0, 1, 1, 'observed', 'fixture', 'x', 'x'),
              ('mapping-linux', 'linux-b', 'linuxbox', 'bob', 'codex', 'codex-main',
               'codex', 'cli', '2026-07-01T09:00:00+08:00',
               '2026-07-01T10:00:00+08:00', 'Asia/Shanghai', 1, 0, 0, 0,
               0, 1, 0.0, 1, 1, 'observed', 'fixture', 'x', 'x');

            INSERT INTO usage_daily_rollups (
              date, bucket_start, bucket_end, source_id, machine_id, os_user,
              ai_provider, ai_account_id, agent, client, attribution_confidence,
              provenance, input_tokens, output_tokens, cache_creation_tokens,
              cache_read_tokens, reasoning_output_tokens, total_tokens,
              event_count, session_count, fact_count
            ) VALUES (
              '2026-05-20', '2026-05-20T00:00:00+08:00',
              '2026-05-20T23:59:59+08:00', 'mac-a', 'macbook', 'alice',
              'claude', 'claude-main', 'claude', 'cli', 'observed', 'fixture',
              150, 30, 20, 0, 0, 200, 1, 1, 1
            );
            """
        )
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
