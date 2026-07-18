from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget.mswusage_codex import build_report, read_local_codex_jsonl_lines


FIXTURES = Path(__file__).parent / "fixtures"
FORBIDDEN_MARKERS = [
    ".codex",
    ".claude",
    ".jsonl",
    "/Users/",
    "/home/",
    "~",
    "codex_token_count_sample",
    "secret prompt text",
    "secret response text",
    "secret shell output",
    "not json",
]


class TestMSWusageCodex(unittest.TestCase):
    def test_cumulative_high_water_skips_no_growth_events_with_new_timestamps(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=100),
            _token_event("2026-07-16T01:05:00Z", last_total=60, cumulative_total=100),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 100)
        self.assertEqual(report["collector"]["counts"]["accepted"], 1)
        self.assertEqual(report["collector"]["counts"]["no_growth"], 1)
        self.assertTrue(report["collector"]["scan_complete"])

    def test_cumulative_events_are_sorted_and_only_real_growth_is_counted(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:10:00Z", last_total=60, cumulative_total=160),
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=100),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 160)
        self.assertEqual(report["collector"]["counts"]["accepted"], 2)

    def test_cumulative_reset_starts_a_new_epoch_without_losing_repeated_state(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=100),
            _token_event("2026-07-16T01:05:00Z", last_total=60, cumulative_total=160),
            _token_event("2026-07-16T01:10:00Z", last_total=50, cumulative_total=50),
            _token_event("2026-07-16T01:15:00Z", last_total=50, cumulative_total=100),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 260)
        self.assertEqual(report["collector"]["counts"]["cumulative_reset"], 1)
        self.assertEqual(report["collector"]["counts"]["no_growth"], 0)
        self.assertTrue(report["collector"]["scan_complete"])

    def test_non_contiguous_cumulative_growth_is_diagnostic_not_structural_failure(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=100),
            _token_event("2026-07-16T01:05:00Z", last_total=60, cumulative_total=170),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["collector"]["counts"]["non_contiguous_transition"], 1)
        self.assertEqual(report["collector"]["counts"]["unresolved_mismatch"], 0)
        self.assertTrue(report["collector"]["scan_complete"])

    def test_reset_epoch_allows_old_state_once_then_dedupes_it_again(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=100),
            _token_event("2026-07-16T01:05:00Z", last_total=50, cumulative_total=50),
            _token_event("2026-07-16T01:10:00Z", last_total=50, cumulative_total=100),
            _token_event("2026-07-16T01:15:00Z", last_total=50, cumulative_total=100),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 200)
        self.assertEqual(report["collector"]["counts"]["no_growth"], 1)

    def test_same_total_with_different_complete_state_is_not_deduped(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event_breakdown("2026-07-16T01:00:00Z", 100, 0, 100, 0),
            _token_event_breakdown("2026-07-16T01:05:00Z", 0, 10, 90, 10),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 110)
        self.assertEqual(report["collector"]["counts"]["same_total_state_change"], 1)

    def test_incremental_scan_uses_pre_window_event_as_high_water_seed(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-15T23:55:00Z", last_total=100, cumulative_total=100),
            _token_event("2026-07-16T00:05:00Z", last_total=100, cumulative_total=100),
        ]

        report = build_report(
            lines,
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"),
            since=datetime.fromisoformat("2026-07-16T08:00:00+08:00"),
            mode="incremental",
            lookback_hours=4,
        )

        self.assertEqual(report["daily"], [])
        self.assertEqual(report["collector"]["counts"]["seeded"], 1)
        self.assertEqual(report["collector"]["counts"]["no_growth"], 1)

    def test_unresolved_cumulative_mismatch_blocks_complete_scan(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            _token_event("2026-07-16T01:00:00Z", last_total=100, cumulative_total=50),
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertFalse(report["collector"]["scan_complete"])
        self.assertEqual(report["collector"]["counts"]["unresolved_mismatch"], 1)

    def test_sessionless_active_archive_copy_is_deduped_across_file_scopes(self) -> None:
        event = _token_event("2026-07-16T01:00:00Z", last_total=11, cumulative_total=11)
        lines = [
            '{"type":"mswusage_file_boundary"}',
            event,
            '{"type":"mswusage_file_boundary"}',
            event,
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"))

        self.assertEqual(report["daily"][0]["total_tokens"], 11)
        self.assertEqual(report["collector"]["counts"]["exact_duplicate"], 1)

    def test_read_errors_block_complete_scan(self) -> None:
        report = build_report(
            [],
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-07-16T12:00:00+08:00"),
            read_diagnostics={"files_scanned": 2, "read_errors": 1},
        )

        self.assertFalse(report["collector"]["scan_complete"])
        self.assertEqual(report["collector"]["counts"]["read_errors"], 1)

    def test_explicit_full_rescan_coverage_proves_zero_for_requested_window(self) -> None:
        report = build_report(
            [],
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-07-18T09:15:00+08:00"),
            coverage_start=datetime.fromisoformat("2026-07-12T00:00:00+08:00"),
        )

        self.assertEqual(report["collector"]["coverage"], {
            "start": "2026-07-12T00:00:00+08:00",
            "end": "2026-07-18T10:00:00+08:00",
        })

    def test_missing_codex_roots_are_not_treated_as_verified_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diagnostics = {}
            lines = read_local_codex_jsonl_lines(Path(tmp) / "missing", diagnostics=diagnostics)

        self.assertEqual(lines, [])
        self.assertEqual(diagnostics["read_errors"], 1)

    def test_build_report_buckets_token_count_events_by_local_hour(self) -> None:
        lines = (FIXTURES / "codex_token_count_sample.jsonl").read_text(encoding="utf-8").splitlines()

        report = build_report(
            lines,
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"),
        )

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "mswusage_codex")
        self.assertEqual(report["timezone"], "Asia/Shanghai")
        self.assertEqual(report["generated_at"], "2026-06-05T09:00:00+08:00")
        self.assertEqual(report["provenance"], "mswusage_codex_token_count")
        self.assertEqual([row["hour"] for row in report["hourly"]], [
            "2026-06-04T23:00:00+08:00",
            "2026-06-05T00:00:00+08:00",
            "2026-06-05T01:00:00+08:00",
        ])
        self.assertEqual([row["date"] for row in report["daily"]], ["2026-06-04", "2026-06-05"])
        self.assertEqual([row["total_tokens"] for row in report["hourly"]], [1050, 325, 12])
        self.assertEqual([row["event_count"] for row in report["hourly"]], [1, 1, 1])
        self.assertEqual([row["session_count"] for row in report["hourly"]], [1, 1, 1])
        self.assertEqual(report["daily"][0]["total_tokens"], 1050)
        self.assertEqual(report["daily"][1]["total_tokens"], 337)
        self.assertEqual(report["daily"][1]["event_count"], 2)
        self.assertEqual(report["sessions"][0]["session_id"], "019e91f1-739a-79b1-99ca-60cc89982c35")
        self.assertEqual(report["sessions"][0]["first_event_at"], "2026-06-04T23:58:12+08:00")
        self.assertEqual(report["sessions"][0]["last_event_at"], "2026-06-05T01:01:00+08:00")
        self.assertEqual(report["sessions"][0]["total_tokens"], 1387)
        self.assertEqual(report["sessions"][0]["event_count"], 3)

    def test_token_type_math_treats_cached_input_as_subset(self) -> None:
        lines = (FIXTURES / "codex_token_count_sample.jsonl").read_text(encoding="utf-8").splitlines()

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"))

        first_hour = report["hourly"][0]
        self.assertEqual(first_hour["input_tokens"], 750)
        self.assertEqual(first_hour["cache_read_tokens"], 250)
        self.assertEqual(first_hour["cache_creation_tokens"], 0)
        self.assertEqual(first_hour["output_tokens"], 50)
        self.assertEqual(first_hour["reasoning_output_tokens"], 10)
        for row in report["hourly"] + report["daily"] + report["sessions"]:
            self.assertEqual(
                row["input_tokens"] + row["output_tokens"] + row["cache_creation_tokens"] + row["cache_read_tokens"],
                row["total_tokens"],
            )
            self.assertEqual(row["provenance"], "mswusage_codex_token_count")

    def test_output_does_not_emit_paths_raw_lines_or_message_text(self) -> None:
        lines = (FIXTURES / "codex_token_count_sample.jsonl").read_text(encoding="utf-8").splitlines()

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"))
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)

        for marker in FORBIDDEN_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, output)
        self.assertIn("Asia/Shanghai", output)

    def test_missing_session_meta_uses_safe_fallback_id(self) -> None:
        lines = (FIXTURES / "codex_token_count_without_session.jsonl").read_text(encoding="utf-8").splitlines()

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"))

        self.assertEqual(len(report["sessions"]), 1)
        self.assertRegex(report["sessions"][0]["session_id"], r"^fallback:[0-9a-f]{12}$")
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(".jsonl", output)
        self.assertNotIn("/Users/", output)

    def test_file_boundary_prevents_session_id_leaking_to_next_file(self) -> None:
        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            '{"timestamp":"2026-06-04T08:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":1,"total_tokens":11}}}}',
            '{"type":"mswusage_file_boundary"}',
            '{"timestamp":"2026-06-04T09:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":20,"cached_input_tokens":0,"output_tokens":2,"total_tokens":22}}}}',
        ]

        report = build_report(lines, timezone="Asia/Shanghai", now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"))

        self.assertEqual(len(report["sessions"]), 2)
        self.assertRegex(report["sessions"][0]["session_id"], r"^fallback:[0-9a-f]{12}$")
        self.assertEqual(report["sessions"][1]["session_id"], "session-a")

    def test_shanghai_timezone_fallback_when_zoneinfo_is_unavailable(self) -> None:
        from ai_usage_widget import timezones

        lines = [
            '{"type":"session_meta","payload":{"id":"session-a"}}',
            '{"timestamp":"2026-06-04T16:30:00Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":1,"total_tokens":11}}}}',
        ]

        with patch.object(timezones, "_ZoneInfo", None):
            report = build_report(
                lines,
                timezone="Asia/Shanghai",
                now=datetime.fromisoformat("2026-06-05T09:00:00+08:00"),
            )

        self.assertEqual(report["generated_at"], "2026-06-05T09:00:00+08:00")
        self.assertEqual(report["hourly"][0]["hour"], "2026-06-05T00:00:00+08:00")
        self.assertEqual(report["daily"][0]["date"], "2026-06-05")

    def test_default_local_reader_includes_archived_sessions_without_double_counting_duplicates(self) -> None:
        active_event = '{"timestamp":"2026-06-05T01:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":1,"total_tokens":11}}}}'
        archived_event = '{"timestamp":"2026-06-05T02:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":20,"cached_input_tokens":0,"output_tokens":2,"total_tokens":22}}}}'

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions_dir = home / ".codex" / "sessions"
            archived_dir = home / ".codex" / "archived_sessions"
            sessions_dir.mkdir(parents=True)
            archived_dir.mkdir(parents=True)
            (sessions_dir / "active.jsonl").write_text(
                "\n".join([
                    '{"type":"session_meta","payload":{"id":"session-a"}}',
                    active_event,
                ]),
                encoding="utf-8",
            )
            (archived_dir / "archived.jsonl").write_text(
                "\n".join([
                    '{"type":"session_meta","payload":{"id":"session-a"}}',
                    active_event,
                    archived_event,
                ]),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=home):
                lines = read_local_codex_jsonl_lines()

        report = build_report(
            lines,
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-06-05T12:00:00+08:00"),
        )

        self.assertEqual([row["total_tokens"] for row in report["hourly"]], [11, 22])
        self.assertEqual(report["daily"][0]["total_tokens"], 33)
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("archived_sessions", output)
        self.assertNotIn("active.jsonl", output)


if __name__ == "__main__":
    unittest.main()


def _token_event(timestamp: str, *, last_total: int, cumulative_total: int) -> str:
    return json.dumps({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": last_total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": last_total,
                },
                "total_token_usage": {
                    "input_tokens": cumulative_total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": cumulative_total,
                },
            },
        },
    }, separators=(",", ":"))


def _token_event_breakdown(
    timestamp: str,
    last_input: int,
    last_output: int,
    cumulative_input: int,
    cumulative_output: int,
) -> str:
    return json.dumps({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": last_input,
                    "cached_input_tokens": 0,
                    "output_tokens": last_output,
                    "total_tokens": last_input + last_output,
                },
                "total_token_usage": {
                    "input_tokens": cumulative_input,
                    "cached_input_tokens": 0,
                    "output_tokens": cumulative_output,
                    "total_tokens": cumulative_input + cumulative_output,
                },
            },
        },
    }, separators=(",", ":"))
