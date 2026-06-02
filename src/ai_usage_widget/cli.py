from __future__ import annotations

import argparse
import json
import os
import sys

from .collector import collect
from .config import ConfigError, load_config, validate_device_config
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

    sync_parser = subparsers.add_parser("sync-widget", help="Copy latest.json into the local Widget container")
    sync_parser.add_argument("--input", default="data/latest.json")
    sync_parser.add_argument("--destination", default=None)

    server_parser = subparsers.add_parser("server", help="Start the HTTP Ingest and Web API server")
    server_parser.add_argument("--host", default="127.0.0.1")
    server_parser.add_argument("--port", type=int, default=8000)
    server_parser.add_argument("--db", default="data/usage.sqlite")
    server_parser.add_argument("--latest", default="data/latest.json")
    server_parser.add_argument("--token", default=None, help="Bearer token")
    server_parser.add_argument("--timezone", default="Asia/Shanghai")

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
            result = DevicePusher(device_config).push()
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

    if args.command == "server":
        token = args.token or os.environ.get("AI_USAGE_INGEST_TOKEN")
        try:
            run_server(
                host=args.host,
                port=args.port,
                db_path=args.db,
                latest_path=args.latest,
                token=token,
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
