from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def backup_sqlite(
    db_path: str,
    backup_dir: str,
    timestamp: Optional[str] = None,
    keep: int = 14,
    max_total_mb: int = 512,
) -> Dict[str, Any]:
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
    pruned = prune_backups(destination_dir, source.stem, keep=keep, max_total_mb=max_total_mb)
    return {
        "success": True,
        "db_path": str(source),
        "backup_path": str(destination),
        "size_bytes": size_bytes,
        "pruned_count": len(pruned),
        "pruned_paths": [str(path) for path in pruned],
    }


def prune_backups(backup_dir: Path, db_stem: str, keep: int, max_total_mb: int) -> List[Path]:
    keep = max(1, int(keep))
    max_total_bytes = max(1, int(max_total_mb)) * 1024 * 1024
    candidates = [
        path for path in backup_dir.glob(f"{db_stem}-*.sqlite")
        if path.is_file()
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    kept: List[Path] = []
    pruned: List[Path] = []
    total_bytes = 0
    for path in candidates:
        size = path.stat().st_size
        if len(kept) >= keep or (kept and total_bytes + size > max_total_bytes):
            path.unlink()
            pruned.append(path)
            continue
        kept.append(path)
        total_bytes += size
    return pruned
