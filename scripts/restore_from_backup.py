#!/usr/bin/env python3
"""Validate per-table D1 backup JSON, generate replay SQL, and print Wrangler command."""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
from pathlib import Path
from typing import Any


CANONICAL_TABLES = (
    "usage_hourly_facts",
    "usage_hourly_models",
    "machines",
    "os_identities",
    "ai_accounts",
    "source_identities",
    "limit_windows",
    "usage_daily_rollups",
    "d1_migrations",
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("backup contains a non-finite number")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ValueError(f"backup contains unsupported SQL value type: {type(value).__name__}")


def load_documents(input_dir: Path) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for table in CANONICAL_TABLES:
        path = input_dir / f"{table}.json"
        if not path.is_file():
            raise ValueError(f"missing backup file: {path.name}")
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        rows = document.get("rows")
        if document.get("schema_version") != 1 or document.get("table") != table:
            raise ValueError(f"{path.name} has an invalid schema_version or table name")
        if not isinstance(rows, list) or document.get("row_count") != len(rows):
            raise ValueError(f"{path.name} row_count does not match rows")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"{path.name} rows must all be JSON objects")
        documents[table] = document
    return documents


def build_restore_sql(documents: dict[str, dict[str, Any]]) -> str:
    # D1 wraps `wrangler d1 execute --file` imports itself and rejects explicit
    # BEGIN/COMMIT statements. Keep this file directly importable by Wrangler.
    lines: list[str] = []
    for table in reversed(CANONICAL_TABLES):
        lines.append(f"DELETE FROM {table};")
    for table in CANONICAL_TABLES:
        rows = documents[table]["rows"]
        expected_columns: tuple[str, ...] | None = None
        for row in rows:
            columns = tuple(row.keys())
            if not columns or any(not IDENTIFIER_RE.fullmatch(column) for column in columns):
                raise ValueError(f"{table} contains an invalid column name")
            if expected_columns is None:
                expected_columns = columns
            elif columns != expected_columns:
                raise ValueError(f"{table} rows do not share one column layout")
            values = ", ".join(sql_literal(row[column]) for column in columns)
            lines.append(
                f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({values});"
            )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true")
    mode.add_argument("--remote", action="store_true")
    parser.add_argument("--persist-to")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.persist_to and not args.local:
        raise ValueError("--persist-to is only valid with --local")
    documents = load_documents(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_restore_sql(documents), encoding="utf-8")

    command = [
        "npx", "wrangler", "d1", "execute", args.database,
        "--config", args.config,
        "--local" if args.local else "--remote",
    ]
    if args.persist_to:
        command.extend(["--persist-to", args.persist_to])
    command.extend(["--file", str(args.output), "--yes"])
    print(shlex.join(command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
