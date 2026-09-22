"""Local-only owner-generated payloads and real Python outbox → HTTP regression.

Only command execution/time are deterministic substitutes. Payload construction,
SQLite outbox, HTTP client, response classification and ACK are production code.
No persisted golden and no user/provider files are read.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.collector_store import CollectorStore
from ai_usage_widget.models import CommandResult
from ai_usage_widget.pusher import DevicePusher, IngestHTTPClient

TOKEN = "contract-test-token"


class CaptureHTTP(IngestHTTPClient):
    def __init__(self, real=False):
        self.real = real
        self.payloads = []
        self.acknowledged = []

    def post(self, url, data, headers, timeout):
        self.payloads.append(data)
        status, body = super().post(url, data, {**headers, "Authorization": f"Bearer {TOKEN}"}, timeout) if self.real else (200, {"status": "accepted"})
        if status == 200:
            self.acknowledged.append(data)
        return status, body


def push(spec, client, url, store=None):
    agent = spec.get("agent", "codex")
    provenance = f"mswusage_{agent}_" + ("token_count" if agent == "codex" else "assistant_usage")
    report = {
        "schema_version": 1, "source": f"mswusage_{agent}", "provenance": provenance,
        "generated_at": spec["observed_at"], "daily": [], "sessions": [],
        "hourly": [{"hour": hour, "input_tokens": total, "total_tokens": total, "provenance": spec.get("provenance", provenance)} for hour, total in spec.get("hours", [])],
    }
    if "models" in spec:
        for row in report["hourly"]:
            row["model_breakdowns"] = spec["models"]
    if "collector" in spec:
        report["collector"] = spec["collector"]
    def execute(argv, timeout):
        if f"mswusage-{agent}" in argv:
            return CommandResult(stdout=json.dumps(report), exit_code=0)
        return CommandResult(stdout="{}", exit_code=0)
    config = DeviceConfig(schema_version=1, source_id=spec.get("source_id", "retry-device"),
                          host="test-machine", machine=spec.get("machine", "test-machine"), os_user="tester", platform="linux",
                          timezone="Asia/Shanghai", server_url=url, timeout_seconds=20, token_env=None)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime.fromisoformat(spec["observed_at"])
            return value.astimezone(tz) if tz else value
    pusher = DevicePusher(config, executor=execute, http_client=client, retry_attempts=1, outbox=store)
    with patch("ai_usage_widget.pusher.datetime", FrozenDateTime):
        result = pusher.push()
    return result, pusher


def main():
    specs = json.load(sys.stdin)
    if sys.argv[1] == "legacy-hourly":
        from ai_usage_widget.d1_legacy_backfill import BackfillOptions, _hourly_row, _hourly_fact_operation, _hourly_rollup_operation
        operations = []
        for spec in specs:
            date = spec["hour"][:10]
            row = _hourly_row(spec, spec["identity"], BackfillOptions(date, date, date))
            operations.extend([_hourly_fact_operation(row), _hourly_rollup_operation(row)])
        print(json.dumps(operations))
        return
    if sys.argv[1] == "legacy-daily":
        from ai_usage_widget.d1_legacy_backfill import BackfillOptions, _daily_row, _daily_operation
        rows = []
        for spec in specs:
            record = {"date": spec["date"], "source_id": spec["source_id"], "agent": "codex",
                      "input_tokens": spec["tokens"], "total_tokens": spec["tokens"], "output_tokens": 0,
                      "cache_creation_tokens": 0, "cache_read_tokens": 0, "total_cost": None}
            identity = {"machine_id": "test-machine", "os_user": "tester", "ai_provider": "openai", "ai_account_id": "legacy-account"}
            row = _daily_row(record, identity, BackfillOptions(spec["date"], spec["date"], spec["date"]))
            rows.append(_daily_operation(row))
        print(json.dumps(rows))
        return
    if sys.argv[1] == "generate":
        client = CaptureHTTP()
        for spec in specs:
            result, _ = push(spec, client, "http://local.test/ingest")
            assert result["success"], result
        print(json.dumps(client.payloads))
        return
    client = CaptureHTTP(real=True)
    clock = [1000.0]
    with tempfile.TemporaryDirectory(prefix="aiusage-ingest-reliability-") as directory:
        with CollectorStore(Path(directory) / "outbox.sqlite", clock=lambda: clock[0]) as store:
            attempts = []
            for spec in specs:
                result, pusher = push(spec, client, sys.argv[2], store)
                attempts.append({"success": result["success"], "pending": store.pending_count()})
            clock[0] += 3600
            replay = pusher._flush_outbox(store, {}, limit=100)
            store.assert_drained()
            print(json.dumps({"attempts": attempts, "replay": list(replay.values()),
                              "stats": store.stats(), "acknowledged": client.acknowledged}))


if __name__ == "__main__":
    main()
