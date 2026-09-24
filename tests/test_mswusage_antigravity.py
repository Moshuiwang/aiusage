from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from ai_usage_widget.mswusage_antigravity import (
    PROVENANCE,
    build_report,
    read_local_antigravity_events,
)


def _encode_varint(value: int) -> bytes:
    res = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return bytes(res)


def _encode_proto_field(field_num: int, wire_type: int, payload: bytes | int) -> bytes:
    tag = (field_num << 3) | wire_type
    if wire_type == 0:
        return _encode_varint(tag) + _encode_varint(int(payload))
    elif wire_type == 2:
        return _encode_varint(tag) + _encode_varint(len(payload)) + payload
    raise ValueError(f"unsupported wire_type: {wire_type}")


def _build_step_metadata(timestamp_sec: int) -> bytes:
    # Field 7 (or 6): Timestamp message (Field 1: seconds varint)
    ts_msg = _encode_proto_field(1, 0, timestamp_sec)
    return _encode_proto_field(7, 2, ts_msg)


def _build_gen_metadata(
    model: str,
    prompt_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    thoughts_tokens: int,
) -> bytes:
    # UsageMetadata in F4:
    # Field 1: prompt_tokens
    # Field 2: output_tokens
    # Field 5: cached_tokens
    # Field 6: thoughts_tokens
    f4_body = (
        _encode_proto_field(1, 0, prompt_tokens)
        + _encode_proto_field(2, 0, output_tokens)
        + _encode_proto_field(5, 0, cached_tokens)
        + _encode_proto_field(6, 0, thoughts_tokens)
    )
    # F1 in GenMetadata:
    # Field 4: UsageMetadata
    # Field 19: model string
    f1_body = _encode_proto_field(4, 2, f4_body) + _encode_proto_field(19, 2, model.encode("utf-8"))
    # Top level: Field 1 is F1
    return _encode_proto_field(1, 2, f1_body)


class TestMswusageAntigravity(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.conv_dir = Path(self.temp_dir.name) / "conversations"
        self.conv_dir.mkdir(parents=True)

    def _create_sample_db(
        self,
        db_path: Path,
        steps: list[tuple[int, int, str, int, int, int, int]],
    ) -> None:
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute(
                "CREATE TABLE steps (idx integer, step_type integer, status integer, metadata blob, PRIMARY KEY (idx))"
            )
            conn.execute(
                "CREATE TABLE gen_metadata (idx integer, data blob, size integer, PRIMARY KEY (idx))"
            )
            for idx, ts_sec, model, prompt, output, cached, thoughts in steps:
                step_meta = _build_step_metadata(ts_sec)
                gen_meta = _build_gen_metadata(model, prompt, output, cached, thoughts)
                conn.execute("INSERT INTO steps (idx, step_type, status, metadata) VALUES (?, 15, 3, ?)", (idx, step_meta))
                conn.execute("INSERT INTO gen_metadata (idx, data, size) VALUES (?, ?, ?)", (idx, gen_meta, len(gen_meta)))
        conn.close()

    def test_read_local_antigravity_events_and_build_report(self) -> None:
        db_path = self.conv_dir / "test-session-1.db"
        # 2026-09-24T00:15:00 UTC (08:15 CST) -> sec: 1790208900
        # 2026-09-24T00:45:00 UTC (08:45 CST) -> sec: 1790210700
        # 2026-09-24T01:10:00 UTC (09:10 CST) -> sec: 1790212200
        self._create_sample_db(
            db_path,
            [
                (1, 1790208900, "gemini-3.8-flash", 1000, 200, 5000, 50),
                (2, 1790210700, "gemini-3.8-flash", 2000, 300, 6000, 100),
                (3, 1790212200, "gemini-3.1-pro", 3000, 500, 10000, 200),
            ],
        )

        events = read_local_antigravity_events(roots=[self.conv_dir])
        self.assertEqual(len(events), 3)

        report = build_report(events, timezone="Asia/Shanghai")
        self.assertEqual(report["source"], "mswusage_antigravity")
        self.assertEqual(report["provenance"], PROVENANCE)

        # 3 events across 2 hours (08:00 and 09:00 CST)
        self.assertEqual(len(report["hourly"]), 2)
        h0 = report["hourly"][0]
        self.assertEqual(h0["hour"], "2026-09-24T08:00:00+08:00")
        self.assertEqual(h0["input_tokens"], 3000)
        self.assertEqual(h0["output_tokens"], 500)
        self.assertEqual(h0["cache_read_tokens"], 11000)
        self.assertEqual(h0["reasoning_output_tokens"], 150)
        self.assertEqual(h0["total_tokens"], 14500)  # 3000 + 500 + 11000
        self.assertEqual(h0["model_breakdowns"][0]["model"], "gemini-3.8-flash")
        self.assertEqual(h0["model_breakdowns"][0]["total_tokens"], 14500)

        h1 = report["hourly"][1]
        self.assertEqual(h1["hour"], "2026-09-24T09:00:00+08:00")
        self.assertEqual(h1["input_tokens"], 3000)
        self.assertEqual(h1["output_tokens"], 500)
        self.assertEqual(h1["cache_read_tokens"], 10000)
        self.assertEqual(h1["reasoning_output_tokens"], 200)
        self.assertEqual(h1["total_tokens"], 13500)
        self.assertEqual(h1["model_breakdowns"][0]["model"], "gemini-3.1-pro")
        self.assertEqual(h1["model_breakdowns"][0]["total_tokens"], 13500)

        # Daily bucket
        self.assertEqual(len(report["daily"]), 1)
        d0 = report["daily"][0]
        self.assertEqual(d0["date"], "2026-09-24")
        self.assertEqual(d0["total_tokens"], 28000)

    def test_corrupted_data_and_empty_db_handled_gracefully(self) -> None:
        empty_db = self.conv_dir / "empty.db"
        conn = sqlite3.connect(empty_db)
        with conn:
            conn.execute("CREATE TABLE steps (idx integer, metadata blob)")
            conn.execute("CREATE TABLE gen_metadata (idx integer, data blob)")
        conn.close()

        corrupt_db = self.conv_dir / "corrupted.db"
        conn = sqlite3.connect(corrupt_db)
        with conn:
            conn.execute("CREATE TABLE steps (idx integer, metadata blob)")
            conn.execute("CREATE TABLE gen_metadata (idx integer, data blob)")
            conn.execute("INSERT INTO steps VALUES (1, X'1234')")
            conn.execute("INSERT INTO gen_metadata VALUES (1, X'FFFF')")
        conn.close()

        events = read_local_antigravity_events(roots=[self.conv_dir])
        self.assertEqual(len(events), 0)

        report = build_report(events, timezone="Asia/Shanghai")
        self.assertEqual(len(report["hourly"]), 0)
        self.assertEqual(len(report["daily"]), 0)

    def test_since_filtering(self) -> None:
        db_path = self.conv_dir / "since-test.db"
        self._create_sample_db(
            db_path,
            [
                (1, 1790208900, "gemini-3.8-flash", 1000, 200, 5000, 50),  # 08:15 CST
                (2, 1790212200, "gemini-3.1-pro", 3000, 500, 10000, 200),  # 09:10 CST
            ],
        )
        events = read_local_antigravity_events(roots=[self.conv_dir])
        # filter since 09:00 CST
        since_dt = datetime.fromisoformat("2026-09-24T09:00:00+08:00")
        report = build_report(events, timezone="Asia/Shanghai", since=since_dt)
        self.assertEqual(len(report["hourly"]), 1)
        self.assertEqual(report["hourly"][0]["hour"], "2026-09-24T09:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
