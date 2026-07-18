#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_NAME = "AI Usage Menu Bar"
EXECUTABLE_NAME = "AIUsageMenuBar"
DEFAULT_BUNDLE_ID = "com.chunbai.aiusage.menubar.app"
DEFAULT_INSTALL_DIR = Path("/Applications")


def default_repo_dir() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class InstallPlan:
    repo_dir: Path
    package_dir: Path
    build_binary: Path
    app_path: Path
    executable_path: Path
    source_icon_path: Path
    bundle_icon_path: Path
    runtime_dir: Path
    config_path: Path
    bundle_id: str = DEFAULT_BUNDLE_ID

    @staticmethod
    def default(
        *,
        repo_dir: Path,
        home: Path,
        install_dir: Path | None,
        runtime_dir: Path | None,
        bundle_id: str = DEFAULT_BUNDLE_ID,
    ) -> "InstallPlan":
        package_dir = repo_dir / "clients" / "macos"
        build_binary = package_dir / ".build" / "release" / EXECUTABLE_NAME
        resolved_install_dir = install_dir or DEFAULT_INSTALL_DIR
        app_path = resolved_install_dir / f"{APP_NAME}.app"
        source_icon_path = package_dir / "Resources" / "AIUsageMenuBar.icns"
        resolved_runtime_dir = runtime_dir or home / "Library" / "Application Support" / "ai-usage-widget" / "macos-menu-bar"
        return InstallPlan(
            repo_dir=repo_dir,
            package_dir=package_dir,
            build_binary=build_binary,
            app_path=app_path,
            executable_path=app_path / "Contents" / "MacOS" / EXECUTABLE_NAME,
            source_icon_path=source_icon_path,
            bundle_icon_path=app_path / "Contents" / "Resources" / "AIUsageMenuBar.icns",
            runtime_dir=resolved_runtime_dir,
            config_path=resolved_runtime_dir / "config.json",
            bundle_id=bundle_id,
        )


def render_info_plist(plan: InstallPlan) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>{EXECUTABLE_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>{plan.bundle_id}</string>
  <key>CFBundleName</key>
  <string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>{APP_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>AIUsageMenuBar</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
"""


def sign_app_bundle(plan: InstallPlan) -> None:
    """Bind the installed app to the same stable identity used by macOS settings."""
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            "--identifier",
            plan.bundle_id,
            str(plan.app_path),
        ],
        check=True,
    )


def install(plan: InstallPlan, *, server_url: str | None, token: str | None, dashboard_url: str | None, dry_run: bool) -> dict[str, Any]:
    result = {
        "dry_run": dry_run,
        "package_dir": str(plan.package_dir),
        "app_path": str(plan.app_path),
        "runtime_dir": str(plan.runtime_dir),
        "config_path": str(plan.config_path),
        "token_configured": bool(token),
    }
    if dry_run:
        return result

    subprocess.run(["swift", "build", "-c", "release"], cwd=plan.package_dir, check=True)
    if not plan.build_binary.exists():
        raise FileNotFoundError(plan.build_binary)

    if plan.app_path.exists():
        shutil.rmtree(plan.app_path)
    (plan.app_path / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (plan.app_path / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan.build_binary, plan.executable_path)
    plan.executable_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    if plan.source_icon_path.exists():
        shutil.copy2(plan.source_icon_path, plan.bundle_icon_path)
    (plan.app_path / "Contents" / "Info.plist").write_text(render_info_plist(plan), encoding="utf-8")
    sign_app_bundle(plan)

    plan.runtime_dir.mkdir(parents=True, exist_ok=True)
    if server_url or token or dashboard_url:
        current = _read_config(plan.config_path)
        if server_url:
            current["server_url"] = server_url
        if token:
            current["token"] = token
        if dashboard_url:
            current["dashboard_url"] = dashboard_url
        current.setdefault("refresh_interval_seconds", 600)
        current.setdefault("default_period", "today")
        _write_private_json(plan.config_path, current)

    return result


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"config must be an object: {path}")
    return payload


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and install the AI Usage macOS menu bar app.")
    parser.add_argument("--repo-dir", default=str(default_repo_dir()))
    parser.add_argument("--install-dir", default=None)
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--server-url", default=os.environ.get("AI_USAGE_API_BASE_URL"))
    parser.add_argument("--dashboard-url", default=os.environ.get("AI_USAGE_DASHBOARD_URL"))
    parser.add_argument("--token-env", default="AI_USAGE_INGEST_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--launch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = Path.home()
    plan = InstallPlan.default(
        repo_dir=Path(args.repo_dir).expanduser().resolve(),
        home=home,
        install_dir=Path(args.install_dir).expanduser() if args.install_dir else None,
        runtime_dir=Path(args.runtime_dir).expanduser() if args.runtime_dir else None,
        bundle_id=args.bundle_id,
    )
    token = os.environ.get(args.token_env, "")
    result = install(
        plan,
        server_url=args.server_url,
        token=token or None,
        dashboard_url=args.dashboard_url,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.launch and not args.dry_run:
        subprocess.run(["open", str(plan.app_path)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
