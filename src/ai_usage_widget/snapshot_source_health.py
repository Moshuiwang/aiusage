from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .snapshot_filters import identity_matches_filter


def build_source_status(
    *,
    status_rows: list[Any],
    source_identities: dict[str, dict[str, Any]],
    sources_config: Optional[list[dict[str, Any]]],
    ref_time: datetime,
    machine_filter: Optional[str] = None,
    account_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    db_status = {sr[0]: {"status": sr[1], "collected_at": sr[2], "error_message": sr[3]} for sr in status_rows}
    if machine_filter or account_filter:
        db_status = {
            sid: status
            for sid, status in db_status.items()
            if identity_matches_filter(source_identities.get(sid), machine_filter, account_filter)
        }

    source_status = []
    if sources_config:
        for source_config in sources_config:
            source_id = source_config["source_id"]
            stale_threshold = int(source_config.get("stale_after_minutes", 120))
            if source_id not in db_status:
                source_status.append(_source_status_entry(
                    {
                        "source_id": source_id,
                        "status": "never_seen",
                        "observed_at": None,
                        "error_message": None,
                    },
                    source_identities.get(source_id),
                    source_config,
                ))
                continue

            last_report = db_status[source_id]
            status_value = _status_with_staleness(
                last_report["status"],
                last_report["collected_at"],
                ref_time,
                stale_threshold,
            )
            source_status.append(_source_status_entry(
                {
                    "source_id": source_id,
                    "status": status_value,
                    "observed_at": last_report["collected_at"],
                    "error_message": last_report.get("error_message"),
                },
                source_identities.get(source_id),
                source_config,
            ))
        return source_status

    for source_id, last_report in db_status.items():
        status_value = _status_with_staleness(
            last_report["status"],
            last_report["collected_at"],
            ref_time,
            120,
        )
        source_status.append(_source_status_entry(
            {
                "source_id": source_id,
                "status": status_value,
                "observed_at": last_report["collected_at"],
                "error_message": last_report.get("error_message"),
            },
            source_identities.get(source_id),
        ))
    return source_status


def _status_with_staleness(
    status: str,
    collected_at: str,
    ref_time: datetime,
    stale_threshold_minutes: int,
) -> str:
    collected_time = datetime.fromisoformat(collected_at)
    diff_minutes = (ref_time - collected_time).total_seconds() / 60.0
    if diff_minutes > stale_threshold_minutes:
        return "stale"
    return status


def _source_status_entry(
    status: dict[str, Any],
    identity: Optional[dict[str, Any]] = None,
    source_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    result = dict(status)
    identity = identity or {}
    source_config = source_config or {}
    host = identity.get("host") or identity.get("machine") or source_config.get("host") or source_config.get("host_label")
    os_user = identity.get("os_user") or source_config.get("os_user") or source_config.get("account")
    platform = identity.get("platform") or source_config.get("platform")

    if host:
        result["host"] = str(host)
    if os_user:
        result["os_user"] = str(os_user)
    if platform:
        result["platform"] = str(platform)
    if host and os_user:
        result["display_name"] = f"{host} · {os_user}"
    elif host:
        result["display_name"] = str(host)
    else:
        result["display_name"] = str(result.get("source_id") or "unknown-source")
    return result
