from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from .collector import collect
from .backup import backup_sqlite
from .config import ConfigError, load_config, validate_device_config
from .claude_limits_provider import ClaudeCliUsageProvider, ClaudeOAuthProvider, ClaudeOAuthWithCliFallbackProvider
from .codex_limits_provider import CodexAppServerRPCProvider, CodexWhamProvider, CodexWhamWithRPCFallbackProvider
from .lock import FileLock, LockAlreadyHeld
from .limits_config import ConfigError as LimitsConfigError, LimitsProviderConfig, load_limits_config, summarize_limits_config
from .limits_doctor import run_limits_doctor
from .limits_runtime import LimitsRuntime, load_fixture_providers
from .limits_push import push_limits_payload
from .limits_scheduler import LimitsSchedulerConfig, install_limits_scheduler
from .mswusage_codex import build_report as build_mswusage_codex_report, read_local_codex_jsonl_lines
from .mswusage_claude import build_report as build_mswusage_claude_report, read_local_claude_jsonl_lines
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
    push_parser.add_argument(
        "--ledger-mode",
        choices=["incremental", "full-rescan"],
        default="incremental",
        help="Usage Ledger collection mode; daily schedulers should keep incremental",
    )
    push_parser.add_argument(
        "--ledger-lookback-hours",
        type=float,
        default=48.0,
        help="Incremental Usage Ledger lookback window",
    )

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
    limits_parser.add_argument("--doctor", action="store_true", help="Run redacted readiness checks before real provider smoke")

    push_limits_parser = subparsers.add_parser("push-limits", help="Collect official limits facts and push them to the ingest server")
    push_limits_parser.add_argument("--provider", action="append", dest="providers", help="Provider to collect, repeatable")
    push_limits_parser.add_argument("--limits-config", default=None, help="Local limits provider config JSON")
    push_limits_parser.add_argument("--provider-fixture", default=None, help="Offline fixture with provider windows")
    push_limits_parser.add_argument("--url", required=True, help="Limits ingest endpoint URL")
    push_limits_parser.add_argument("--token-env", default="AI_USAGE_INGEST_TOKEN", help="Environment variable containing the bearer token")
    push_limits_parser.add_argument("--timeout", type=float, default=10.0)
    push_limits_parser.add_argument("--timezone", default=None)
    push_limits_parser.add_argument("--dry-run", action="store_true", help="Collect and validate without posting")
    push_limits_parser.add_argument("--lock-file", default=None, help="Optional single-instance lock file")

    install_limits_scheduler_parser = subparsers.add_parser(
        "install-limits-scheduler",
        help="Install a macOS LaunchAgent for periodic limits push",
    )
    install_limits_scheduler_parser.add_argument("--repo-dir", default=os.getcwd())
    install_limits_scheduler_parser.add_argument("--limits-config", default=None)
    install_limits_scheduler_parser.add_argument("--url", required=True)
    install_limits_scheduler_parser.add_argument("--token-env", default="AI_USAGE_INGEST_TOKEN")
    install_limits_scheduler_parser.add_argument("--token-env-file", default=None)
    install_limits_scheduler_parser.add_argument("--runner-path", default=None)
    install_limits_scheduler_parser.add_argument("--plist-path", default=None)
    install_limits_scheduler_parser.add_argument("--log-dir", default=None)
    install_limits_scheduler_parser.add_argument("--lock-file", default=None)
    install_limits_scheduler_parser.add_argument("--label", default="com.chunbai.aiusage.limits-push")
    install_limits_scheduler_parser.add_argument("--interval-seconds", type=int, default=1800)
    install_limits_scheduler_parser.add_argument("--python", default="/usr/bin/python3")
    install_limits_scheduler_parser.add_argument("--dry-run", action="store_true")

    mswusage_codex_parser = subparsers.add_parser(
        "mswusage-codex",
        help="Build a local Codex hourly usage report from token_count events",
    )
    mswusage_codex_parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    mswusage_codex_parser.add_argument("--timezone", default="Asia/Shanghai")
    mswusage_codex_parser.add_argument("--mode", choices=["incremental", "full-rescan"], default="full-rescan")
    mswusage_codex_parser.add_argument("--lookback-hours", type=float, default=48.0)
    mswusage_codex_parser.add_argument("--no-include-archived", action="store_true", help="Skip archived Codex sessions")

    mswusage_claude_parser = subparsers.add_parser(
        "mswusage-claude",
        help="Build a local Claude hourly usage report from assistant usage events",
    )
    mswusage_claude_parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    mswusage_claude_parser.add_argument("--timezone", default="Asia/Shanghai")
    mswusage_claude_parser.add_argument("--mode", choices=["incremental", "full-rescan"], default="full-rescan")
    mswusage_claude_parser.add_argument("--lookback-hours", type=float, default=48.0)

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
                    result = DevicePusher(
                        device_config,
                        ledger_mode=args.ledger_mode,
                        ledger_lookback_hours=args.ledger_lookback_hours,
                    ).push()
            else:
                result = DevicePusher(
                    device_config,
                    ledger_mode=args.ledger_mode,
                    ledger_lookback_hours=args.ledger_lookback_hours,
                ).push()
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
            if args.doctor:
                report = run_limits_doctor(args.limits_config)
                print(json.dumps(report, ensure_ascii=False, sort_keys=True))
                return 0 if report["success"] else 1
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
                [_provider_runtime_key(provider) for provider in limits_config.enabled_providers] if limits_config else sorted(providers)
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

    if args.command == "push-limits":
        try:
            if args.lock_file:
                with FileLock(args.lock_file):
                    output, success = _run_push_limits(args)
            else:
                output, success = _run_push_limits(args)
        except LockAlreadyHeld as exc:
            print(json.dumps({"success": False, "error_type": "lock_already_held", "error_message": str(exc)}), file=sys.stderr)
            return 1
        except (OSError, ValueError, LimitsConfigError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0 if success else 1

    if args.command == "install-limits-scheduler":
        try:
            scheduler_config = _limits_scheduler_config_from_args(args)
            result = install_limits_scheduler(
                scheduler_config,
                env=os.environ,
                dry_run=args.dry_run,
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "mswusage-codex":
        try:
            now = datetime.now(dt_timezone.utc).astimezone()
            since = _usage_ledger_since(args.mode, args.lookback_hours, now)
            lines = read_local_codex_jsonl_lines(
                include_archived=not args.no_include_archived,
                modified_since=since,
            )
            report = build_mswusage_codex_report(lines, timezone=args.timezone, now=now, since=since)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "mswusage-claude":
        try:
            now = datetime.now(dt_timezone.utc).astimezone()
            since = _usage_ledger_since(args.mode, args.lookback_hours, now)
            lines = read_local_claude_jsonl_lines(modified_since=since)
            report = build_mswusage_claude_report(lines, timezone=args.timezone, now=now, since=since)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
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


def _providers_from_limits_config(configs: list[LimitsProviderConfig]):
    providers = {}
    for provider_config in configs:
        runtime_key = _provider_runtime_key(provider_config)
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
                providers[runtime_key] = _tag_provider(
                    CodexWhamWithRPCFallbackProvider(
                        wham_provider=codex_wham_provider,
                        rpc_provider=codex_rpc_provider,
                    ),
                    provider_name="codex",
                    source_id=runtime_key,
                )
            elif codex_wham_provider:
                providers[runtime_key] = _tag_provider(codex_wham_provider, provider_name="codex", source_id=runtime_key)
            elif codex_rpc_provider:
                providers[runtime_key] = _tag_provider(codex_rpc_provider, provider_name="codex", source_id=runtime_key)
        elif provider_config.provider == "claude":
            claude_oauth_provider = (
                ClaudeOAuthProvider(
                    auth_file=provider_config.auth_file,
                    usage_url=provider_config.usage_url,
                )
                if provider_config.auth_file and provider_config.usage_url
                else None
            )
            claude_cli_provider = (
                ClaudeCliUsageProvider(env=provider_config.env)
                if provider_config.claude_cli
                else None
            )
            if claude_oauth_provider and claude_cli_provider:
                providers[runtime_key] = _tag_provider(
                    ClaudeOAuthWithCliFallbackProvider(
                        oauth_provider=claude_oauth_provider,
                        cli_provider=claude_cli_provider,
                    ),
                    provider_name="claude",
                    source_id=runtime_key,
                )
            elif claude_oauth_provider:
                providers[runtime_key] = _tag_provider(claude_oauth_provider, provider_name="claude", source_id=runtime_key)
            elif claude_cli_provider:
                providers[runtime_key] = _tag_provider(claude_cli_provider, provider_name="claude", source_id=runtime_key)
    return providers


def _usage_ledger_since(mode: str, lookback_hours: float, now: datetime) -> datetime | None:
    if mode == "full-rescan":
        return None
    return now - timedelta(hours=max(float(lookback_hours), 1.0))


def _provider_runtime_key(provider_config: LimitsProviderConfig) -> str:
    return provider_config.source_id or provider_config.provider


def _tag_provider(provider, *, provider_name: str, source_id: str):
    setattr(provider, "provider_name", provider_name)
    setattr(provider, "source_id", source_id)
    return provider


def _run_push_limits(args):
    limits_config = load_limits_config(args.limits_config) if args.limits_config else None
    providers = load_fixture_providers(args.provider_fixture) if args.provider_fixture else {}
    if limits_config:
        providers.update(_providers_from_limits_config(limits_config.enabled_providers))
    provider_names = args.providers or (
        [_provider_runtime_key(provider) for provider in limits_config.enabled_providers] if limits_config else sorted(providers)
    )
    runtime = LimitsRuntime(
        db_path=limits_config.sqlite_path if limits_config else "data/usage.sqlite",
        latest_path=limits_config.latest_path if limits_config else "data/latest.json",
        timezone=args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
        providers=providers,
    )
    result = runtime.collect(
        provider_names=provider_names,
        rebuild_snapshot=False,
        dry_run=True,
    )
    payload = {
        "schema_version": 1,
        "observed_at": _limits_payload_observed_at(result.windows),
        "timezone": args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
        "windows": [window.to_snapshot_dict() for window in result.windows],
    }
    push_response = None
    if not args.dry_run:
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ValueError(f"missing push token env: {args.token_env}")
        push_response = push_limits_payload(args.url, token, payload, timeout=args.timeout)

    output = {
        "success": result.success,
        "dry_run": args.dry_run,
        "windows_collected": len(result.windows),
        "providers": [
            {
                "provider": item.provider,
                "status": item.status,
                "windows_collected": _count_windows_for_provider(result.windows, item.provider),
                "error_type": item.error_type,
            }
            for item in result.provider_results
        ],
    }
    if push_response is not None:
        output["push"] = push_response
        output["windows_written"] = push_response.get("windows_written")
    return output, result.success


def _limits_payload_observed_at(windows) -> str:
    observed = sorted({window.observed_at for window in windows if window.observed_at})
    if observed:
        return observed[-1]
    return datetime.now(dt_timezone.utc).astimezone().isoformat()


def _count_windows_for_provider(windows, provider: str) -> int:
    return len([window for window in windows if window.source_id == provider or window.provider == provider])


def _limits_scheduler_config_from_args(args) -> LimitsSchedulerConfig:
    home = Path.home()
    repo_dir = Path(args.repo_dir).expanduser()
    label = args.label
    return LimitsSchedulerConfig(
        repo_dir=repo_dir,
        limits_config=Path(args.limits_config).expanduser() if args.limits_config else repo_dir / "config/limits.local.json",
        url=args.url,
        token_env_file=Path(args.token_env_file).expanduser()
        if args.token_env_file
        else home / "Library/Application Support/ai-usage-widget/limits-push.env",
        runner_path=Path(args.runner_path).expanduser()
        if args.runner_path
        else home / "Library/Application Support/ai-usage-widget/limits-push.sh",
        plist_path=Path(args.plist_path).expanduser()
        if args.plist_path
        else home / "Library/LaunchAgents" / f"{label}.plist",
        log_dir=Path(args.log_dir).expanduser() if args.log_dir else home / "Library/Logs/ai-usage-widget",
        lock_file=Path(args.lock_file).expanduser()
        if args.lock_file
        else home / "Library/Caches/ai-usage-widget/limits-push.lock",
        label=label,
        interval_seconds=args.interval_seconds,
        python_executable=args.python,
        token_env_name=args.token_env,
        path_value=os.environ.get("PATH"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
