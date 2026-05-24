from __future__ import annotations

import argparse
import sys

from .collector import collect
from .config import ConfigError, load_config
from .widget_sync import sync_latest_to_widget


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-usage-widget")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Collect ccusage daily reports")
    collect_parser.add_argument("--config", default="config/sources.local.json")
    collect_parser.add_argument("--output", default="data/latest.json")
    collect_parser.add_argument("--sqlite", default="data/usage.sqlite")
    collect_parser.add_argument("--sync-widget", action="store_true", help="Copy latest.json into the local Widget container")

    sync_parser = subparsers.add_parser("sync-widget", help="Copy latest.json into the local Widget container")
    sync_parser.add_argument("--input", default="data/latest.json")
    sync_parser.add_argument("--destination", default=None)

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

    if args.command == "sync-widget":
        try:
            destination = sync_latest_to_widget(args.input, args.destination)
            print(f"synced widget snapshot: {destination}")
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
