from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from ai_usage_widget.mswusage_codex import build_report


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


if __name__ == "__main__":
    unittest.main()
