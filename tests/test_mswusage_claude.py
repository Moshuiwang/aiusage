from __future__ import annotations

import json
import unittest
from datetime import datetime

from ai_usage_widget.mswusage_claude import build_report


FORBIDDEN_MARKERS = [
    ".claude",
    ".codex",
    ".jsonl",
    "/Users/",
    "/home/",
    "~",
    "secret prompt text",
    "secret response text",
]


class TestMSWusageClaude(unittest.TestCase):
    def test_build_report_dedupes_assistant_message_by_message_id_and_request_id(self) -> None:
        lines = [
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-06-05T01:00:00Z",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    "content": "secret response text",
                },
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-06-05T01:02:00Z",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus",
                    "usage": {
                        "input_tokens": 150,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    "content": "secret response text",
                },
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-06-05T02:00:00Z",
                "requestId": "req-2",
                "message": {
                    "id": "msg-2",
                    "model": "claude-sonnet",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_creation_input_tokens": 7,
                        "cache_read_input_tokens": 8,
                    },
                },
                "prompt": "secret prompt text",
            }),
        ]

        report = build_report(
            lines,
            timezone="Asia/Shanghai",
            now=datetime.fromisoformat("2026-06-05T12:00:00+08:00"),
        )

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "mswusage_claude")
        self.assertEqual(report["provenance"], "mswusage_claude_assistant_usage")
        self.assertEqual([row["hour"] for row in report["hourly"]], [
            "2026-06-05T09:00:00+08:00",
            "2026-06-05T10:00:00+08:00",
        ])
        self.assertEqual([row["total_tokens"] for row in report["hourly"]], [170, 30])
        self.assertEqual(report["daily"][0]["total_tokens"], 200)
        self.assertEqual(report["daily"][0]["event_count"], 2)
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)
        for marker in FORBIDDEN_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, output)


if __name__ == "__main__":
    unittest.main()
