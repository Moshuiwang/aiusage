#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


PRODUCTION_BASE_URL = "https://vpn2.chunbai.com:8443"
SUMMARY_SMOKE_PATH = "/api/mobile/summary?period=all"
DEFAULT_DEVICE_ID = "00008140-0002792C1AFB001C"
DEFAULT_DEVICECTL_ID = "EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6"
APP_BUNDLE_ID = "com.wangzhipeng.aiusage.mobile"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build, verify, install, and launch the iOS app with live production config."
    )
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID, help="xcodebuild destination device id")
    parser.add_argument("--devicectl-id", default=DEFAULT_DEVICECTL_ID, help="devicectl device id")
    parser.add_argument("--token-env", default="AI_USAGE_INGEST_TOKEN", help="environment variable containing token")
    parser.add_argument("--token-file", default=None, help="0600 file containing token; never printed")
    parser.add_argument("--token-ssh-host", default="vpn2", help="SSH host used as final token fallback")
    parser.add_argument("--preflight-only", action="store_true", help="verify token and production API without building")
    parser.add_argument("--skip-launch", action="store_true", help="install only")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    project_dir = root / "mobile" / "ios-xcode"
    project = project_dir / "AIUsageMobile.xcodeproj"

    token = read_token(args.token_env, args.token_file, args.token_ssh_host)
    verify_production_summary(token)
    if args.preflight_only:
        print("预检完成：生产 token 和移动端接口可用。")
        return 0

    secret_paths: list[Path] = []
    try:
        xcconfig = write_temp_xcconfig(token)
        secret_paths.append(xcconfig)
        app_path = build_app(project=project, device_id=args.device_id, xcconfig=xcconfig)
        verify_built_app_config(app_path)
        install_app(app_path=app_path, devicectl_id=args.devicectl_id)
        if not args.skip_launch:
            launch_app(devicectl_id=args.devicectl_id)
    finally:
        cleanup_secret_files(secret_paths)

    print("真机安装完成：生产接口已验证，App 包配置已验证，token 未显示。")
    return 0


def read_token(token_env: str, token_file: str | None, token_ssh_host: str | None) -> str:
    token = ""
    if token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        token = os.environ.get(token_env, "").strip()
    if not token:
        token = read_token_from_vpn2_systemd(token_ssh_host)
    if not token:
        raise RuntimeError(f"missing token: set {token_env}, pass --token-file, or configure vpn2 SSH")
    return token


def read_token_from_vpn2_systemd(token_ssh_host: str | None) -> str:
    if not token_ssh_host:
        return ""
    command = [
        "ssh",
        token_ssh_host,
        "systemctl",
        "show",
        "ai-usage-server",
        "-p",
        "Environment",
        "--value",
    ]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return ""
    for part in result.stdout.split():
        if part.startswith("AI_USAGE_INGEST_TOKEN="):
            return part.split("=", 1)[1].strip()
    return ""


def verify_production_summary(token: str) -> None:
    request = urllib.request.Request(
        PRODUCTION_BASE_URL + SUMMARY_SMOKE_PATH,
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"production summary smoke failed: HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"production summary smoke failed: {type(exc).__name__}") from exc

    summary = payload.get("summary")
    metric_source = summary if isinstance(summary, dict) else payload.get("period")
    if not isinstance(metric_source, dict):
        raise RuntimeError("production summary smoke failed: unexpected response shape")
    total_tokens = metric_source.get("total_tokens")
    if not isinstance(total_tokens, int):
        raise RuntimeError("production summary smoke failed: total_tokens missing")
    if not isinstance(payload.get("trend"), dict) or not isinstance(payload.get("breakdown"), dict):
        raise RuntimeError("production summary smoke failed: trend or breakdown missing")

    period = payload.get("period", {})
    period_id = period.get("id") if isinstance(period, dict) else period
    print(f"生产接口验证通过：period={period_id} total_tokens={total_tokens}")


def write_temp_xcconfig(token: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="ai-usage-mobile-secrets-",
        suffix=".xcconfig",
        delete=False,
    )
    path = Path(handle.name)
    try:
        os.chmod(path, 0o600)
        handle.write("AI_USAGE_API_BASE_URL = https:/$()/vpn2.chunbai.com:8443\n")
        handle.write(f"AI_USAGE_API_TOKEN = {token}\n")
    finally:
        handle.close()
    return path


def build_app(project: Path, device_id: str, xcconfig: Path) -> Path:
    command = [
        "xcodebuild",
        "-project",
        str(project),
        "-scheme",
        "AIUsageMobileApp",
        "-destination",
        f"id={device_id}",
        "-configuration",
        "Debug",
        "-xcconfig",
        str(xcconfig),
        "clean",
        "build",
    ]
    run(command)
    app_path = latest_built_app()
    print(f"真机包构建完成：{app_path}")
    return app_path


def latest_built_app() -> Path:
    derived_data = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    candidates = sorted(
        derived_data.glob("AIUsageMobile-*/Build/Products/Debug-iphoneos/AIUsageMobileApp.app"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("built app not found")
    return candidates[0]


def verify_built_app_config(app_path: Path) -> None:
    plist_path = app_path / "Info.plist"
    info = plistlib.loads(plist_path.read_bytes())
    base_url = info.get("AIUsageAPIBaseURL")
    token = info.get("AIUsageAPIToken")
    token_length = len(token or "")
    if base_url != PRODUCTION_BASE_URL:
        raise RuntimeError(f"refusing to install: AIUsageAPIBaseURL is {base_url!r}")
    if token_length <= 0:
        raise RuntimeError("refusing to install: AIUsageAPIToken is empty")
    print(f"App 包配置验证通过：baseURL={base_url} token_length={token_length}")


def install_app(app_path: Path, devicectl_id: str) -> None:
    run(["xcrun", "devicectl", "device", "install", "app", "--device", devicectl_id, str(app_path)])
    print("App 已安装到真机。")


def launch_app(devicectl_id: str) -> None:
    run(["xcrun", "devicectl", "device", "process", "launch", "--device", devicectl_id, APP_BUNDLE_ID])
    print("App 已启动。")


def run(command: list[str]) -> None:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        raise RuntimeError(f"command failed: {command[0]}")


def cleanup_secret_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
