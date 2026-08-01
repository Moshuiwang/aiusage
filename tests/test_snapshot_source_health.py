from __future__ import annotations

import unittest
from datetime import datetime

from ai_usage_widget import version_contract
from ai_usage_widget.snapshot_source_health import build_source_status


class TestSnapshotSourceHealth(unittest.TestCase):
    def test_build_source_status_keeps_stale_ok_and_never_seen_contract(self) -> None:
        status_rows = [
            ("mac-local", "ok", "2026-06-01T08:00:00+08:00", None),
            ("linux-server", "ok", "2026-06-01T10:40:00+08:00", None),
        ]
        source_identities = {
            "mac-local": {"host": "macbook", "os_user": "wang", "platform": "macos"},
            "linux-server": {"host": "linux-dev", "os_user": "ubuntu", "platform": "linux"},
        }
        sources_config = [
            {"source_id": "mac-local", "stale_after_minutes": 60},
            {"source_id": "linux-server", "stale_after_minutes": 120},
            {"source_id": "windows-desktop", "host_label": "winbox", "os_user": "dev", "stale_after_minutes": 120},
        ]

        source_status = build_source_status(
            status_rows=status_rows,
            source_identities=source_identities,
            sources_config=sources_config,
            ref_time=datetime.fromisoformat("2026-06-01T10:50:00+08:00"),
        )

        self.assertEqual(len(source_status), 3)
        by_source = {row["source_id"]: row for row in source_status}

        self.assertEqual(by_source["mac-local"]["status"], "stale")
        self.assertEqual(by_source["mac-local"]["observed_at"], "2026-06-01T08:00:00+08:00")
        self.assertEqual(by_source["mac-local"]["display_name"], "macbook · wang")
        self.assertEqual(by_source["mac-local"]["platform"], "macos")

        self.assertEqual(by_source["linux-server"]["status"], "ok")
        self.assertEqual(by_source["linux-server"]["display_name"], "linux-dev · ubuntu")

        self.assertEqual(by_source["windows-desktop"]["status"], "never_seen")
        self.assertIsNone(by_source["windows-desktop"]["observed_at"])
        self.assertEqual(by_source["windows-desktop"]["display_name"], "winbox · dev")

    def test_build_source_status_respects_machine_and_account_filters(self) -> None:
        status_rows = [
            ("linux-dev-wang", "ok", "2026-06-01T10:40:00+08:00", None),
            ("linux-dev-ubuntu", "ok", "2026-06-01T10:45:00+08:00", None),
        ]
        source_identities = {
            "linux-dev-wang": {"machine": "linux-dev", "os_user": "wang"},
            "linux-dev-ubuntu": {"machine": "linux-dev", "os_user": "ubuntu"},
        }

        source_status = build_source_status(
            status_rows=status_rows,
            source_identities=source_identities,
            sources_config=None,
            ref_time=datetime.fromisoformat("2026-06-01T10:50:00+08:00"),
            machine_filter="linux-dev",
            account_filter="wang",
        )

        self.assertEqual([row["source_id"] for row in source_status], ["linux-dev-wang"])

    def test_build_source_status_keeps_machine_separate_from_network_host(self) -> None:
        source_status = build_source_status(
            status_rows=[("tz-wang", "ok", "2026-06-01T10:40:00+08:00", None)],
            source_identities={
                "tz-wang": {
                    "machine": "tz",
                    "host": "wrong-network-host",
                    "os_user": "wang",
                    "platform": "linux",
                }
            },
            sources_config=None,
            ref_time=datetime.fromisoformat("2026-06-01T10:50:00+08:00"),
        )

        self.assertEqual(
            source_status[0],
            {
                "source_id": "tz-wang",
                "status": "ok",
                "observed_at": "2026-06-01T10:40:00+08:00",
                "error_message": None,
                "machine": "tz",
                "host": "wrong-network-host",
                "os_user": "wang",
                "platform": "linux",
                "display_name": "tz · wang",
            },
        )


class TestSnapshotSourceHealthVersions(unittest.TestCase):
    def _build(self, source_versions):
        return build_source_status(
            status_rows=[
                ("old-box", "ok", "2026-06-01T10:40:00+08:00", None),
                ("new-box", "ok", "2026-06-01T10:41:00+08:00", None),
                ("mute-box", "ok", "2026-06-01T10:42:00+08:00", None),
            ],
            source_identities={},
            sources_config=None,
            ref_time=datetime.fromisoformat("2026-06-01T10:50:00+08:00"),
            source_versions=source_versions,
            version_policy=version_contract.VersionPolicy(
                min_supported_collector_version="0.2.0",
                target_collector_version="0.4.0",
            ),
        )

    def test_version_state_is_derived_for_every_source_with_a_reported_version(self) -> None:
        rows = {row["source_id"]: row for row in self._build({
            "old-box": {"collector_version": "0.3.0"},
            "new-box": {"collector_version": "0.9.0"},
        })}

        self.assertEqual(rows["old-box"]["version"]["state"], "update_available")
        self.assertEqual(rows["old-box"]["version"]["collector_version"], "0.3.0")
        self.assertEqual(rows["new-box"]["version"]["state"], "rollback_available")

    def test_source_that_never_reported_a_version_is_unknown_not_assumed_compliant(self) -> None:
        rows = {row["source_id"]: row for row in self._build({"old-box": {"collector_version": "0.3.0"}})}

        self.assertEqual(rows["mute-box"]["version"]["state"], "unknown")
        self.assertEqual(rows["mute-box"]["version"]["reason"], "collector_release_missing")
        self.assertFalse(rows["mute-box"]["version"]["verified"])

    def test_version_block_keeps_a_stable_key_set_for_downstream_consumers(self) -> None:
        rows = self._build({"old-box": {"collector_version": "0.3.0"}})

        expected = set(version_contract.COLLECTOR_VERSION_FIELDS) | {
            "state",
            "reason",
            "compatible",
            "verified",
            "min_supported_collector_version",
            "target_collector_version",
            "rollback_target_version",
        }
        for row in rows:
            with self.subTest(source_id=row["source_id"]):
                self.assertEqual(set(row["version"]), expected)

    def test_version_block_is_omitted_when_no_version_data_is_supplied_at_all(self) -> None:
        rows = build_source_status(
            status_rows=[("old-box", "ok", "2026-06-01T10:40:00+08:00", None)],
            source_identities={},
            sources_config=None,
            ref_time=datetime.fromisoformat("2026-06-01T10:50:00+08:00"),
        )

        self.assertNotIn("version", rows[0])


if __name__ == "__main__":
    unittest.main()
