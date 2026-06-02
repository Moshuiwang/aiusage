from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional


def backup_sqlite(db_path: str, backup_dir: str, timestamp: Optional[str] = None) -> Dict[str, Any]:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(dt_timezone.utc).astimezone().strftime("%Y-%m-%dT%H-%M-%S")
    destination = destination_dir / f"{source.stem}-{stamp}{source.suffix}"

    with sqlite3.connect(source) as src:
        src.execute("PRAGMA busy_timeout=5000;")
        integrity = src.execute("PRAGMA integrity_check;").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"SQLite integrity_check failed: {integrity}")
        with sqlite3.connect(destination) as dst:
            src.backup(dst)

    size_bytes = os.path.getsize(destination)
    return {
        "success": True,
        "db_path": str(source),
        "backup_path": str(destination),
        "size_bytes": size_bytes,
    }
