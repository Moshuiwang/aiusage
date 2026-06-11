from __future__ import annotations

import json
from typing import Any, Optional


def daily_row_matches_filter(row: Any, machine_filter: Optional[str], account_filter: Optional[str]) -> bool:
    metadata = metadata_from_str(row[9] if len(row) > 9 else None)
    identity = {
        "host": metadata.get("machine") or metadata.get("host") or row[0],
        "os_user": metadata.get("account") or metadata.get("os_user") or "unknown",
    }
    return identity_matches_filter(identity, machine_filter, account_filter)


def timed_row_matches_filter(row: Any, machine_filter: Optional[str], account_filter: Optional[str]) -> bool:
    metadata = metadata_from_str(row[-1] if len(row) > 0 else None)
    identity = {
        "host": metadata.get("machine") or metadata.get("host") or row[0],
        "os_user": metadata.get("account") or metadata.get("os_user") or "unknown",
    }
    return identity_matches_filter(identity, machine_filter, account_filter)


def identity_matches_filter(
    identity: Optional[dict[str, Any]],
    machine_filter: Optional[str],
    account_filter: Optional[str],
) -> bool:
    identity = identity or {}
    machine = str(identity.get("machine") or identity.get("host") or "")
    account = str(identity.get("os_user") or identity.get("account") or "")
    if machine_filter and machine != machine_filter:
        return False
    if account_filter and account != account_filter:
        return False
    return True


def metadata_from_str(metadata_str: Any) -> dict[str, Any]:
    if not metadata_str:
        return {}
    try:
        metadata = json.loads(metadata_str)
    except (TypeError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}
