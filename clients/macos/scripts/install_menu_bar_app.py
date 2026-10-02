#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
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
        resolved_install_dir = install_dir or DEFAULT_INSTALL_DIR
        app_path = resolved_install_dir / f"{APP_NAME}.app"
        source_icon_path = package_dir / "Resources" / "AIUsageMenuBar.icns"
        resolved_runtime_dir = runtime_dir or home / "Library" / "Application Support" / "ai-usage-widget" / "macos-menu-bar"
        return InstallPlan(
            repo_dir=repo_dir,
            package_dir=package_dir,
            app_path=app_path,
            executable_path=app_path / "Contents" / "MacOS" / EXECUTABLE_NAME,
            source_icon_path=source_icon_path,
            bundle_icon_path=app_path / "Contents" / "Resources" / "AIUsageMenuBar.icns",
            runtime_dir=resolved_runtime_dir,
            config_path=resolved_runtime_dir / "config.json",
            bundle_id=bundle_id,
        )


def read_short_version(package_dir: Path) -> str:
    """VERSION 文件缺失时保留旧默认值，不让安装因此失败。"""
    version_path = package_dir / "VERSION"
    if not version_path.exists():
        return "0.1.0"
    text = version_path.read_text(encoding="utf-8").strip()
    return text or "0.1.0"


def git_build_number(repo_dir: Path) -> str:
    """构建号 = 提交计数；git 不可用或不是仓库时回退 "0"，不阻塞安装。"""
    try:
        output = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_dir, check=True, capture_output=True, text=True,
        )
        return str(int(output.stdout.strip()))
    except Exception:
        return "0"


def git_short_commit(repo_dir: Path) -> str | None:
    """短 commit sha；git 不可用时返回 None（省略 Info.plist 里的自定义键）。"""
    try:
        output = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, check=True, capture_output=True, text=True,
        )
        sha = output.stdout.strip()
        return sha or None
    except Exception:
        return None


def git_build_sha(repo_dir: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True)
        value = result.stdout.strip()
        return value if re.fullmatch(r"[a-f0-9]{40,64}", value) else None
    except Exception:
        return None


def render_info_plist(plan: InstallPlan) -> str:
    short_version = read_short_version(plan.package_dir)
    build_number = git_build_number(plan.repo_dir)
    commit_sha = git_short_commit(plan.repo_dir)
    build_sha = git_build_sha(plan.repo_dir)
    build_sha_key = f"  <key>AIUsageBuildSHA</key>\n  <string>{build_sha}</string>\n" if build_sha else ""
    commit_key = (
        f"  <key>AIUsageGitCommit</key>\n  <string>{commit_sha}</string>\n"
        if commit_sha
        else ""
    )
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
  <string>{short_version}</string>
  <key>CFBundleVersion</key>
  <string>{build_number}</string>
{commit_key}{build_sha_key}  <key>LSMinimumSystemVersion</key>
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
            "--deep",
            "--sign",
            "-",
            "--identifier",
            plan.bundle_id,
            str(plan.app_path),
        ],
        check=True,
    )


def build_collector(plan: InstallPlan) -> Path:
    build_dir = plan.package_dir / ".build" / "collector"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "AIUsageCollector", "--paths", str(plan.repo_dir / "src"),
        "--distpath", str(build_dir / "dist"), "--workpath", str(build_dir / "work"),
        "--specpath", str(build_dir), str(plan.package_dir / "scripts" / "collector_entry.py"),
    ], check=True)
    return build_dir / "dist" / "AIUsageCollector.app"


def embed_collector(app_path: Path, frozen_dir: Path) -> None:
    if not (frozen_dir / "Contents" / "MacOS" / "AIUsageCollector").is_file():
        raise FileNotFoundError("frozen collector executable is missing")
    shutil.copytree(frozen_dir, app_path / "Contents" / "Helpers" / "AIUsageCollector.app", symlinks=True)


def import_existing_collector(*, home: Path, runtime_dir: Path) -> bool:
    """Import local settings only. Activation and legacy scheduler handoff are separate."""
    old_config = home / "Library/Application Support/AIUsageWidget/config"
    device_path = old_config / "device.json"
    if not device_path.is_file():
        return False
    folder = runtime_dir / "collector"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, source in (
        ("device.json", device_path),
        ("limits.json", home / "Library/Application Support/ai-usage-widget/runtime/limits.local.json"),
    ):
        if name == "limits.json" and not source.is_file():
            source = old_config / "limits.json"
        destination = folder / name
        if source.is_file() and not destination.exists():
            _write_private_json(destination, _read_config(source))
    return True


def install(plan: InstallPlan, *, server_url: str | None, token: str | None, dashboard_url: str | None, dry_run: bool, collector_bundle: Path | None = None) -> dict[str, Any]:
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

    sdk_args = ["--sdk", os.environ["AI_USAGE_SWIFT_SDK"]] if os.environ.get("AI_USAGE_SWIFT_SDK") else []
    subprocess.run(["swift", "build", "-c", "release"] + sdk_args, cwd=plan.package_dir, check=True)
    output = subprocess.run(
        ["swift", "build", "-c", "release", "--show-bin-path"] + sdk_args,
        cwd=plan.package_dir, check=True, capture_output=True, text=True,
    )
    build_binary = Path(output.stdout.strip()) / EXECUTABLE_NAME
    if not build_binary.is_absolute() or not build_binary.is_file():
        raise FileNotFoundError(build_binary)

    frozen_dir = collector_bundle or build_collector(plan)
    if not (frozen_dir / "Contents" / "MacOS" / "AIUsageCollector").is_file():
        raise FileNotFoundError("frozen collector executable is missing")

    plan.app_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aiusage-install-", dir=plan.app_path.parent) as folder:
        staged_app = Path(folder) / plan.app_path.name
        staged_plan = replace(
            plan, app_path=staged_app,
            executable_path=staged_app / "Contents/MacOS" / EXECUTABLE_NAME,
            bundle_icon_path=staged_app / "Contents/Resources/AIUsageMenuBar.icns",
        )
        (staged_app / "Contents/MacOS").mkdir(parents=True)
        (staged_app / "Contents/Resources").mkdir(parents=True)
        shutil.copy2(build_binary, staged_plan.executable_path)
        staged_plan.executable_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        if plan.source_icon_path.exists():
            shutil.copy2(plan.source_icon_path, staged_plan.bundle_icon_path)
        (staged_app / "Contents/Info.plist").write_text(render_info_plist(plan), encoding="utf-8")
        embed_collector(staged_app, frozen_dir)
        sign_app_bundle(staged_plan)
        previous = Path(folder) / "previous.app"
        if plan.app_path.exists():
            os.replace(plan.app_path, previous)
        try:
            os.replace(staged_app, plan.app_path)
        except OSError:
            if previous.exists():
                os.replace(previous, plan.app_path)
            raise

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
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and install the AI Usage macOS menu bar app.")
    parser.add_argument("--repo-dir", default=str(default_repo_dir()))
    parser.add_argument("--install-dir", default=None)
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--collector-bundle", type=Path, help="Prebuilt frozen collector folder; otherwise build with PyInstaller")
    parser.add_argument("--import-existing-collector", action="store_true", help="Copy existing user collector configuration without enabling collection or changing launchd")
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
        collector_bundle=args.collector_bundle,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.import_existing_collector and not args.dry_run:
        import_existing_collector(home=home, runtime_dir=plan.runtime_dir)
    if args.launch and not args.dry_run:
        subprocess.run(["open", str(plan.app_path)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
