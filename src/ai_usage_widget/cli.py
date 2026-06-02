from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from .collector import collect
from .backup import backup_sqlite
from .config import ConfigError, load_config, validate_device_config
from .lock import FileLock, LockAlreadyHeld
from .pusher import DevicePusher
from .server import run_server
from .widget_sync import sync_latest_to_widget


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-usage-widget")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Collect ccusage daily reports")
    collect_parser.add_argument("--config", default="config/sources.local.json")
    collect_parser.add_argument("--output", default="data/latest.json")
    collect_parser.add_argument("--sqlite", default="data/usage.sqlite")
    collect_parser.add_argument("--sync-widget", action="store_true", help="Copy latest.json into the local Widget container")

    push_parser = subparsers.add_parser("push", help="Collect local ccusage daily report and push it to the ingest server")
    push_parser.add_argument("--config", default="config/sources.local.json")
    push_parser.add_argument("--lock-file", default=None, help="Optional single-instance lock file")

    sync_parser = subparsers.add_parser("sync-widget", help="Copy latest.json into the local Widget container")
    sync_parser.add_argument("--input", default="data/latest.json")
    sync_parser.add_argument("--destination", default=None)

    server_parser = subparsers.add_parser("server", help="Start the HTTP Ingest and Web API server")
    server_parser.add_argument("--host", default="127.0.0.1")
    server_parser.add_argument("--port", type=int, default=8000)
    server_parser.add_argument("--db", default="data/usage.sqlite")
    server_parser.add_argument("--latest", default="data/latest.json")
    server_parser.add_argument("--token", default=None, help="Bearer token")
    server_parser.add_argument("--tokens-env", default="AI_USAGE_INGEST_TOKENS", help="Comma-separated token list env")
    server_parser.add_argument("--timezone", default="Asia/Shanghai")

    backup_parser = subparsers.add_parser("backup", help="Create a safe SQLite backup")
    backup_parser.add_argument("--db", default="data/usage.sqlite")
    backup_parser.add_argument("--backup-dir", default="data/backups")

    args = parser.parse_args(argv)
    if args.command == "collect":
        try:
            config = load_config(args.config)
            collect(config, args.output, args.sqlite)
            if args.sync_widget:
                destination = sync_latest_to_widget(args.output)
                print(f"synced widget snapshot: {destination}")
        except (ConfigError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "push":
        try:
            with open(args.config, "r", encoding="utf-8") as handle:
                config_data = json.load(handle)
            device_config = validate_device_config(config_data)
            if args.lock_file:
                with FileLock(args.lock_file):
                    result = DevicePusher(device_config).push()
            else:
                result = DevicePusher(device_config).push()
        except LockAlreadyHeld as exc:
            print(json.dumps({"success": False, "error_type": "lock_already_held", "error_message": str(exc)}), file=sys.stderr)
            return 1
        except (ConfigError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        output = json.dumps(result, ensure_ascii=False, sort_keys=True)
        if result.get("success"):
            print(output)
            return 0
        print(output, file=sys.stderr)
        return 1

    if args.command == "sync-widget":
        try:
            destination = sync_latest_to_widget(args.input, args.destination)
            print(f"synced widget snapshot: {destination}")
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "backup":
        try:
            result = backup_sqlite(args.db, args.backup_dir)
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "server":
        token = args.token or os.environ.get("AI_USAGE_INGEST_TOKEN")
        token_specs = os.environ.get(args.tokens_env) if args.tokens_env else None
        try:
            run_server(
                host=args.host,
                port=args.port,
                db_path=args.db,
                latest_path=args.latest,
                token=token,
                token_specs=token_specs,
                timezone=args.timezone,
            )
        except Exception as exc:
            print(f"server error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
