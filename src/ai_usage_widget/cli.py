from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from .collector import collect
from .backup import backup_sqlite
from .config import ConfigError, load_config, validate_device_config
from .claude_limits_provider import ClaudeCliUsageProvider, ClaudeOAuthProvider, ClaudeOAuthWithCliFallbackProvider
from .codex_limits_provider import CodexAppServerRPCProvider, CodexWhamProvider, CodexWhamWithRPCFallbackProvider
from .lock import FileLock, LockAlreadyHeld
from .limits_config import ConfigError as LimitsConfigError, LimitsProviderConfig, load_limits_config, summarize_limits_config
from .limits_runtime import LimitsRuntime, load_fixture_providers
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
    backup_parser.add_argument("--keep", type=int, default=14, help="Number of backups to keep")
    backup_parser.add_argument("--max-total-mb", type=int, default=512, help="Maximum backup directory size")

    limits_parser = subparsers.add_parser("collect-limits", help="Collect official limits facts into SQLite")
    limits_parser.add_argument("--provider", action="append", dest="providers", help="Provider to collect, repeatable")
    limits_parser.add_argument("--limits-config", default=None, help="Local limits provider config JSON")
    limits_parser.add_argument("--provider-fixture", default=None, help="Offline fixture with provider windows")
    limits_parser.add_argument("--codex-auth-file", default=None, help="Explicit Codex auth JSON path for WHAM usage")
    limits_parser.add_argument("--codex-rpc", action="store_true", help="Use explicit Codex app-server RPC fallback")
    limits_parser.add_argument("--codex-rpc-sock", default=None, help="Explicit Codex app-server Unix socket path")
    limits_parser.add_argument("--claude-auth-file", default=None, help="Explicit Claude auth JSON path for OAuth usage")
    limits_parser.add_argument("--claude-usage-url", default=None, help="Explicit Claude OAuth usage URL")
    limits_parser.add_argument("--claude-cli", action="store_true", help="Use explicit Claude CLI /usage fallback")
    limits_parser.add_argument("--sqlite", default=None)
    limits_parser.add_argument("--latest", default=None)
    limits_parser.add_argument("--timezone", default=None)
    limits_parser.add_argument("--date", default=None, help="Snapshot date in YYYY-MM-DD")
    limits_parser.add_argument("--no-snapshot", action="store_true", help="Do not rebuild latest snapshot")
    limits_parser.add_argument("--dry-run", action="store_true", help="Collect and validate without writing SQLite or latest snapshot")
    limits_parser.add_argument("--check-config", action="store_true", help="Validate limits config and print a redacted provider plan")

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
            result = backup_sqlite(args.db, args.backup_dir, keep=args.keep, max_total_mb=args.max_total_mb)
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "collect-limits":
        try:
            limits_config = load_limits_config(args.limits_config) if args.limits_config else None
            if args.check_config:
                if limits_config is None:
                    raise ValueError("check-config requires --limits-config")
                summary = summarize_limits_config(limits_config)
                print(json.dumps({
                    "success": True,
                    "check_config": True,
                    **summary,
                }, ensure_ascii=False, sort_keys=True))
                return 0
            providers = load_fixture_providers(args.provider_fixture) if args.provider_fixture else {}
            if limits_config:
                providers.update(_providers_from_limits_config(limits_config.enabled_providers))
            if args.codex_auth_file:
                codex_wham_provider = CodexWhamProvider(auth_file=args.codex_auth_file)
                if args.codex_rpc:
                    providers["codex"] = CodexWhamWithRPCFallbackProvider(
                        wham_provider=codex_wham_provider,
                        rpc_provider=CodexAppServerRPCProvider(socket_path=args.codex_rpc_sock),
                    )
                else:
                    providers["codex"] = codex_wham_provider
            elif args.codex_rpc:
                providers["codex"] = CodexAppServerRPCProvider(socket_path=args.codex_rpc_sock)
            if args.claude_auth_file or args.claude_usage_url:
                if not args.claude_auth_file or not args.claude_usage_url:
                    raise ValueError("claude provider requires both --claude-auth-file and --claude-usage-url")
                claude_oauth_provider = ClaudeOAuthProvider(
                    auth_file=args.claude_auth_file,
                    usage_url=args.claude_usage_url,
                )
                if args.claude_cli:
                    providers["claude"] = ClaudeOAuthWithCliFallbackProvider(
                        oauth_provider=claude_oauth_provider,
                        cli_provider=ClaudeCliUsageProvider(),
                    )
                else:
                    providers["claude"] = claude_oauth_provider
            elif args.claude_cli:
                providers["claude"] = ClaudeCliUsageProvider()
            if args.providers and "codex" in args.providers and "codex" not in providers:
                raise ValueError("codex provider requires --codex-auth-file, --codex-rpc, or --provider-fixture")
            if args.providers and "claude" in args.providers and "claude" not in providers:
                raise ValueError("claude provider requires --claude-auth-file and --claude-usage-url, --claude-cli, or --provider-fixture")
            provider_names = args.providers or (
                [provider.provider for provider in limits_config.enabled_providers] if limits_config else sorted(providers)
            )
            runtime = LimitsRuntime(
                db_path=args.sqlite or (limits_config.sqlite_path if limits_config else "data/usage.sqlite"),
                latest_path=args.latest or (limits_config.latest_path if limits_config else "data/latest.json"),
                timezone=args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
                providers=providers,
            )
            result = runtime.collect(
                provider_names=provider_names,
                rebuild_snapshot=not args.no_snapshot,
                snapshot_date=args.date,
                dry_run=args.dry_run,
            )
        except (OSError, ValueError, LimitsConfigError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "success": result.success,
            "dry_run": args.dry_run,
            "windows_written": result.windows_written,
            "providers": [
                {
                    "provider": item.provider,
                    "status": item.status,
                    "windows_written": item.windows_written,
                    "error_type": item.error_type,
                }
                for item in result.provider_results
            ],
        }, ensure_ascii=False, sort_keys=True))
        return 0 if result.success else 1

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


def _providers_from_limits_config(configs: list[LimitsProviderConfig]):
    providers = {}
    for provider_config in configs:
        if provider_config.provider == "codex":
            codex_wham_provider = (
                CodexWhamProvider(auth_file=provider_config.auth_file)
                if provider_config.auth_file
                else None
            )
            codex_rpc_provider = (
                CodexAppServerRPCProvider(socket_path=provider_config.codex_rpc_sock)
                if provider_config.codex_rpc
                else None
            )
            if codex_wham_provider and codex_rpc_provider:
                providers["codex"] = CodexWhamWithRPCFallbackProvider(
                    wham_provider=codex_wham_provider,
                    rpc_provider=codex_rpc_provider,
                )
            elif codex_wham_provider:
                providers["codex"] = codex_wham_provider
            elif codex_rpc_provider:
                providers["codex"] = codex_rpc_provider
        elif provider_config.provider == "claude":
            claude_oauth_provider = (
                ClaudeOAuthProvider(
                    auth_file=provider_config.auth_file,
                    usage_url=provider_config.usage_url,
                )
                if provider_config.auth_file and provider_config.usage_url
                else None
            )
            claude_cli_provider = ClaudeCliUsageProvider() if provider_config.claude_cli else None
            if claude_oauth_provider and claude_cli_provider:
                providers["claude"] = ClaudeOAuthWithCliFallbackProvider(
                    oauth_provider=claude_oauth_provider,
                    cli_provider=claude_cli_provider,
                )
            elif claude_oauth_provider:
                providers["claude"] = claude_oauth_provider
            elif claude_cli_provider:
                providers["claude"] = claude_cli_provider
    return providers


if __name__ == "__main__":
    raise SystemExit(main())
