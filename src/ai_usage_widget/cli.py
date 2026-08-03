from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from .backup import backup_sqlite
from .config import ConfigError, validate_device_config
from .claude_limits_provider import ClaudeCliUsageProvider, ClaudeOAuthProvider, ClaudeOAuthWithCliFallbackProvider
from .codex_limits_provider import CodexAppServerRPCProvider, CodexWhamProvider, CodexWhamWithRPCFallbackProvider
from .deploy_doctor import (
    EXIT_DOCTOR_ERROR,
    TIMER_SCOPES,
    TIMER_SCOPE_USER,
    DoctorPreconditionError,
    run_deploy_doctor,
)
from . import deploy_release as deploy_release_module
from .deploy_release import ReleaseError, ReleasePlan, install_release, rollback_release
from .deploy_units import CollectorUnitSpec
from .lock import FileLock, LockAlreadyHeld
from .limits_config import ConfigError as LimitsConfigError, LimitsProviderConfig, load_limits_config, summarize_limits_config
from .limits_doctor import run_limits_doctor
from .limits_runtime import LimitsRuntime, load_fixture_providers
from .collector_store import CollectorStore, OutboxNotDrained
from .limits_push import deliver_limits_payload, post_limits_payload, push_limits_payload
from .limits_scheduler import LimitsSchedulerConfig, install_limits_scheduler
from .mswusage_codex import build_report as build_mswusage_codex_report, read_local_codex_jsonl_lines
from .mswusage_claude import build_report as build_mswusage_claude_report, read_local_claude_jsonl_lines
from .pusher import DevicePusher
from .verify_cloud import register_parser as register_verify_cloud_parser, run as run_verify_cloud


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-usage-widget")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    push_parser.add_argument("--ledger-coverage-start", default=None, help="Authoritative full-rescan coverage start")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="采集端部署只读预检：网络入口、入口防护、认证、设备身份、时区、运行目录版本、PYTHONPATH 与定时任务",
    )
    doctor_parser.add_argument("--config", default="config/sources.local.json", help="设备推送配置")
    doctor_parser.add_argument("--environment-fixture", default=None, help="离线重放用的环境事实 JSON")
    doctor_parser.add_argument("--release-dir", default=None, help="运行中的 release 目录（含 release.json）")
    doctor_parser.add_argument("--timer-unit", default=None, help="要检查的 systemd timer 单元名")
    doctor_parser.add_argument(
        "--timer-scope",
        choices=list(TIMER_SCOPES),
        default=TIMER_SCOPE_USER,
        help="timer 所在的 systemd manager 作用域（BIAI 多用户采集器是 system）",
    )
    doctor_parser.add_argument("--timeout", type=float, default=10.0)

    install_collector_parser = subparsers.add_parser(
        "install-collector",
        help="幂等安装/升级采集端 release，并生成、启用 timer 与 service（重复执行不产生重复 timer）",
    )
    install_collector_parser.add_argument("--root", required=True, help="部署根目录")
    install_collector_parser.add_argument("--version", required=True, help="release 版本号，发布后不复用")
    install_collector_parser.add_argument("--revision", required=True, help="对应的代码 revision")
    install_collector_parser.add_argument("--source-id", required=True, help="来源标识，决定单元名")
    install_collector_parser.add_argument(
        "--source-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="要打进 release 的源码目录（默认当前仓库 src）",
    )
    install_collector_parser.add_argument(
        "--unit-dir",
        default=str(Path.home() / ".config/systemd/user"),
        help="systemd 单元目录",
    )
    install_collector_parser.add_argument(
        "--device-config",
        default=None,
        help="首次安装用来生成设备配置的 JSON；已存在的配置永远不会被覆盖",
    )
    install_collector_parser.add_argument(
        "--timer-scope", choices=list(TIMER_SCOPES), default=TIMER_SCOPE_USER
    )
    install_collector_parser.add_argument("--on-calendar", default="*:0/30")
    install_collector_parser.add_argument("--python", default="/usr/bin/python3")
    install_collector_parser.add_argument("--dry-run", action="store_true", help="只回报计划，不改任何文件")

    rollback_collector_parser = subparsers.add_parser(
        "rollback-collector",
        help="回滚到上一个采集端 release 与 timer（不修改用户配置）",
    )
    rollback_collector_parser.add_argument("--root", required=True, help="部署根目录")
    rollback_collector_parser.add_argument(
        "--unit-dir",
        default=str(Path.home() / ".config/systemd/user"),
        help="systemd 单元目录",
    )
    rollback_collector_parser.add_argument(
        "--timer-scope",
        choices=list(TIMER_SCOPES),
        default=None,
        help="默认沿用上一个 release 记录的 scope",
    )

    backup_parser = subparsers.add_parser("backup", help="Create a safe SQLite backup")
    backup_parser.add_argument("--db", default="data/usage.sqlite")
    backup_parser.add_argument("--backup-dir", default="data/backups")
    backup_parser.add_argument("--keep", type=int, default=14, help="Number of backups to keep")
    backup_parser.add_argument("--max-total-mb", type=int, default=512, help="Maximum backup directory size")

    limits_parser = subparsers.add_parser("collect-limits", help="Collect official limits facts and print them (no local persistence; push-limits uploads to D1)")
    limits_parser.add_argument("--provider", action="append", dest="providers", help="Provider to collect, repeatable")
    limits_parser.add_argument("--limits-config", default=None, help="Local limits provider config JSON")
    limits_parser.add_argument("--provider-fixture", default=None, help="Offline fixture with provider windows")
    limits_parser.add_argument("--codex-auth-file", default=None, help="Explicit Codex auth JSON path for WHAM usage")
    limits_parser.add_argument("--codex-rpc", action="store_true", help="Use explicit Codex app-server RPC fallback")
    limits_parser.add_argument("--codex-rpc-sock", default=None, help="Explicit Codex app-server Unix socket path")
    limits_parser.add_argument("--claude-auth-file", default=None, help="Explicit Claude auth JSON path for OAuth usage")
    limits_parser.add_argument("--claude-usage-url", default=None, help="Explicit Claude OAuth usage URL")
    limits_parser.add_argument("--claude-cli", action="store_true", help="Use explicit Claude CLI /usage fallback")
    limits_parser.add_argument("--timezone", default=None)
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
    push_limits_parser.add_argument(
        "--config",
        default=None,
        help=(
            "设备配置（含 outbox 块）。给了就走本地 outbox：断网时额度观测先落盘、"
            "网络恢复后补推；不给则保持原来的直推行为。"
        ),
    )

    outbox_status_parser = subparsers.add_parser(
        "outbox-status", help="查看本地 outbox 还剩多少未投递数据"
    )
    outbox_status_parser.add_argument("--config", default="config/sources.local.json")

    outbox_export_parser = subparsers.add_parser(
        "outbox-export", help="把未投递数据导出成 JSON（不删除任何东西）"
    )
    outbox_export_parser.add_argument("--config", default="config/sources.local.json")
    outbox_export_parser.add_argument("--dest", required=True, help="导出文件路径")

    outbox_drain_parser = subparsers.add_parser(
        "outbox-drain", help="导出后清空未投递数据（关闭 outbox 前的回退演练）"
    )
    outbox_drain_parser.add_argument("--config", default="config/sources.local.json")
    outbox_drain_parser.add_argument("--export-to", required=True, help="清空前先导出到这个文件")
    outbox_drain_parser.add_argument(
        "--yes", action="store_true", help="确认清空。没有它就只导出不清空——不提供无条件清空的入口"
    )

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
    mswusage_codex_parser.add_argument("--coverage-start", default=None)
    mswusage_codex_parser.add_argument("--no-include-archived", action="store_true", help="Skip archived Codex sessions")

    mswusage_claude_parser = subparsers.add_parser(
        "mswusage-claude",
        help="Build a local Claude hourly usage report from assistant usage events",
    )
    mswusage_claude_parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    mswusage_claude_parser.add_argument("--timezone", default="Asia/Shanghai")
    mswusage_claude_parser.add_argument("--mode", choices=["incremental", "full-rescan"], default="full-rescan")
    mswusage_claude_parser.add_argument("--lookback-hours", type=float, default=48.0)
    mswusage_claude_parser.add_argument("--coverage-start", default=None)

    register_verify_cloud_parser(subparsers)

    args = parser.parse_args(argv)
    if args.command == "verify-cloud":
        return run_verify_cloud(args)

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
                        ledger_coverage_start=args.ledger_coverage_start,
                    ).push()
            else:
                result = DevicePusher(
                    device_config,
                    ledger_mode=args.ledger_mode,
                    ledger_lookback_hours=args.ledger_lookback_hours,
                    ledger_coverage_start=args.ledger_coverage_start,
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

    if args.command == "doctor":
        try:
            report = run_deploy_doctor(
                config_path=args.config,
                environment_fixture=args.environment_fixture,
                release_dir=args.release_dir,
                timer_unit=args.timer_unit,
                timer_scope=args.timer_scope,
                timeout=args.timeout,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # DoctorPreconditionError 的消息由代码写死、不含配置内容，可以安全外显；
            # 其他异常只给类型，避免把配置或凭据回显进日志。
            detail = (
                str(exc)
                if isinstance(exc, DoctorPreconditionError)
                else "doctor 前置检查失败，未能采集到判定所需事实"
            )
            print(json.dumps({
                "doctor": "deploy",
                "ok": False,
                "reason_code": "doctor_failed",
                "category": "doctor",
                "exit_code": EXIT_DOCTOR_ERROR,
                "error_type": exc.__class__.__name__,
                "detail": detail,
                "checks": [],
                "failed_reason_codes": [],
            }, ensure_ascii=False, sort_keys=True))
            return EXIT_DOCTOR_ERROR
        print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
        return report.exit_code

    if args.command == "install-collector":
        try:
            plan = _collector_release_plan_from_args(args)
            result = install_release(plan, dry_run=args.dry_run)
        except (ConfigError, ReleaseError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({
                "success": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }, ensure_ascii=False, sort_keys=True))
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("success") else 1

    if args.command == "rollback-collector":
        try:
            result = rollback_release(
                Path(args.root).expanduser(),
                Path(args.unit_dir).expanduser(),
                command_runner=deploy_release_module.default_command_runner,
                timer_scope=args.timer_scope,
            )
        except (ReleaseError, OSError, ValueError) as exc:
            print(json.dumps({
                "success": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }, ensure_ascii=False, sort_keys=True))
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("success") else 1

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
                timezone=args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
                providers=providers,
            )
            result = runtime.collect(provider_names=provider_names)
        except (OSError, ValueError, LimitsConfigError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "success": result.success,
            "windows_collected": len(result.windows),
            "providers": [
                {
                    "provider": item.provider,
                    "status": item.status,
                    "windows_collected": item.windows_collected,
                    "error_type": item.error_type,
                }
                for item in result.provider_results
            ],
        }, ensure_ascii=False, sort_keys=True))
        return 0 if result.success else 1

    if args.command in {"outbox-status", "outbox-export", "outbox-drain"}:
        runner = {
            "outbox-status": _run_outbox_status,
            "outbox-export": _run_outbox_export,
            "outbox-drain": _run_outbox_drain,
        }[args.command]
        try:
            output = runner(args)
        except OutboxNotDrained as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except (ConfigError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

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
            read_diagnostics: dict[str, int] = {}
            lines = read_local_codex_jsonl_lines(
                include_archived=not args.no_include_archived,
                modified_since=since,
                diagnostics=read_diagnostics,
            )
            report = build_mswusage_codex_report(
                lines,
                timezone=args.timezone,
                now=now,
                since=since,
                mode=args.mode,
                lookback_hours=args.lookback_hours,
                read_diagnostics=read_diagnostics,
                coverage_start=_optional_datetime(args.coverage_start),
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "mswusage-claude":
        try:
            now = datetime.now(dt_timezone.utc).astimezone()
            since = _usage_ledger_since(args.mode, args.lookback_hours, now)
            read_diagnostics: dict[str, int] = {}
            lines = read_local_claude_jsonl_lines(modified_since=since, diagnostics=read_diagnostics)
            report = build_mswusage_claude_report(
                lines,
                timezone=args.timezone,
                now=now,
                since=since,
                mode=args.mode,
                lookback_hours=args.lookback_hours,
                read_diagnostics=read_diagnostics,
                coverage_start=_optional_datetime(args.coverage_start),
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
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


def _collector_release_plan_from_args(args) -> ReleasePlan:
    root = Path(args.root).expanduser()
    device_config = None
    if args.device_config:
        with open(Path(args.device_config).expanduser(), "r", encoding="utf-8") as handle:
            device_config = json.load(handle)
        # 种子配置必须先过 owner 模块的校验，别把一份坏配置装到新设备上。
        validate_device_config(device_config)
    return ReleasePlan(
        root=root,
        unit_dir=Path(args.unit_dir).expanduser(),
        source_dir=Path(args.source_dir).expanduser(),
        version=args.version,
        revision=args.revision,
        unit_spec=CollectorUnitSpec(
            source_id=args.source_id,
            release_dir=str(root / "current"),
            config_path=str(root / "config" / "device.json"),
            env_file=str(root / "secrets" / "ingest.env"),
            lock_file=str(root / "run" / "pusher.lock"),
            python_executable=args.python,
            on_calendar=args.on_calendar,
        ),
        device_config=device_config,
        timer_scope=args.timer_scope,
    )


def _usage_ledger_since(mode: str, lookback_hours: float, now: datetime) -> datetime | None:
    if mode == "full-rescan":
        return None
    since = now - timedelta(hours=max(float(lookback_hours), 1.0))
    return since.replace(minute=0, second=0, microsecond=0)


def _optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
        timezone=args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
        providers=providers,
    )
    result = runtime.collect(provider_names=provider_names)
    payload = {
        "schema_version": 1,
        "observed_at": _limits_payload_observed_at(result.windows),
        "timezone": args.timezone or (limits_config.timezone if limits_config else "Asia/Shanghai"),
        "windows": [window.to_snapshot_dict() for window in result.windows],
    }
    push_response = None
    delivered = None
    push_ok = True
    if not args.dry_run:
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ValueError(f"missing push token env: {args.token_env}")
        outbox_config = _outbox_config_for_push_limits(getattr(args, "config", None))
        if outbox_config is None:
            # 没给设备配置（或配置里没有 outbox 块）：保持原来的直推路径，行为零变化。
            push_response = push_limits_payload(args.url, token, payload, timeout=args.timeout)
            delivered = True  # 直推路径失败会抛 ValueError，走不到这里
        else:
            push_response = deliver_limits_payload(
                args.url,
                token,
                payload,
                outbox_config=outbox_config,
                timeout=args.timeout,
                transport=post_limits_payload,
            )
            delivered = bool(push_response.get("delivered"))
            push_ok = _push_is_acceptable(push_response)

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
        output["delivered"] = delivered
        # 直推路径的 push_response 就是服务端 JSON；outbox 路径把它包在 "response" 里。
        output["windows_written"] = (push_response.get("response") or push_response).get("windows_written")
    return output, result.success and push_ok


def _outbox_config_for_push_limits(config_path: str | None):
    """从设备配置里取 outbox 块。没给路径、或配置里没有该块，都返回 ``None``（走直推）。"""
    if not config_path:
        return None
    return _load_device_config(config_path).outbox


def _push_is_acceptable(push_response: dict) -> bool:
    """一次 **outbox 形态**的投递结果算不算「可以退出 0」。

    额度观测**已安全落盘等补推**不算失败：断网是常态，让 LaunchAgent 每次断网都报错，
    真正的故障就会淹没在噪音里。但没落盘也没送到（认证挂了、磁盘满了、终态拒收）
    必须是失败——那种情况下数据是真的没了。
    """
    if push_response.get("delivered"):
        return True
    return bool(push_response.get("queued"))


def _load_device_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as handle:
        return validate_device_config(json.load(handle))


def _require_outbox_config(config_path: str):
    outbox = _load_device_config(config_path).outbox
    if outbox is None:
        raise ValueError(
            f"设备配置 {config_path} 里没有 outbox 块：这台设备从未启用过本地 outbox，"
            "没有未投递数据可查。"
        )
    return outbox


def _run_outbox_status(args) -> dict:
    outbox = _require_outbox_config(args.config)
    path = Path(outbox.path).expanduser()
    if not path.exists():
        # 还没攒下任何东西时库文件根本不存在。这不是故障，也不该顺手把库建出来。
        return {
            "enabled": outbox.enabled,
            "path": str(path),
            "exists": False,
            "undelivered": 0,
            "pending": 0,
            "dead_letters": 0,
            "drained": True,
            "next_step": "本地还没有缓冲任何数据，可以直接关闭 outbox。",
        }
    with CollectorStore.from_config(outbox) as store:
        stats = store.stats()
        undelivered = store.undelivered_count()
        return {
            "enabled": outbox.enabled,
            "path": stats["path"],
            "exists": True,
            "undelivered": undelivered,
            "pending": stats["pending"],
            "dead_letters": stats["dead_letters"],
            "drained": undelivered == 0,
            "used_bytes": stats["used_bytes"],
            "max_bytes": stats["max_bytes"],
            "counters": {key: stats[key] for key in ("enqueued_total", "delivered_total", "expired_total", "dead_letter_total")},
            "next_step": (
                "还有未投递数据。恢复网络后继续上报直到清空；"
                "确实要放弃就先 outbox-export 导出，再 outbox-drain --yes 清空。"
                if undelivered
                else "已排空，可以关闭 outbox 回退到直推。"
            ),
        }


def _run_outbox_export(args) -> dict:
    outbox = _require_outbox_config(args.config)
    with CollectorStore.from_config(outbox) as store:
        exported = store.export_undelivered(args.dest)
    return {
        "exported": exported,
        "dest": str(Path(args.dest).expanduser()),
        # 导出即丢弃是另一种静默丢失，所以这里明说数据还在。
        "note": "导出不删除任何数据；确实要清空请用 outbox-drain --yes。",
    }


def _run_outbox_drain(args) -> dict:
    outbox = _require_outbox_config(args.config)
    with CollectorStore.from_config(outbox) as store:
        exported = store.export_undelivered(args.export_to)
        if not args.yes:
            raise ValueError(
                f"已导出 {exported} 条到 {args.export_to}，但未清空："
                "清空需要显式加 --yes。没有无条件清空的入口。"
            )
        discarded = store.discard_undelivered(exported_to=args.export_to)
    return {
        "exported": exported,
        "discarded": discarded,
        "export_to": str(Path(args.export_to).expanduser()),
    }


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
