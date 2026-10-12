#!/usr/bin/env python3
"""Mac mini release owner: build, sign, upload and verify a draft; never publish it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

GH = "/Users/wangzhipeng/.local/bin/gh-codex-macmini"
GIT = "/Users/wangzhipeng/.local/bin/git-codex-macmini"
REPOSITORY = "Moshuiwang/aiusage"
REQUIRED_CHECKS = {"Python", "Cloudflare Worker", "iOS Swift", "macOS Swift"}


class ReleasePreparationError(RuntimeError):
    pass


def run_command(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ReleasePreparationError("命令执行失败；保留草稿状态，检查权限、构建或网络")
    return result.stdout


def require_release_checks(rows: list[dict]) -> None:
    for name in REQUIRED_CHECKS:
        matches = [row.get("conclusion") for row in rows if row.get("name") == name]
        if matches != ["SUCCESS"]:
            raise ReleasePreparationError("四项必需 CI 必须全部且唯一为 SUCCESS")


def check_release_source(repo: Path, run=run_command) -> str:
    if run(["git", "status", "--porcelain"], repo).strip():
        raise ReleasePreparationError("发布只允许干净工作树")
    head = run(["git", "rev-parse", "HEAD"], repo).strip()
    if head != run(["git", "rev-parse", "origin/main"], repo).strip():
        raise ReleasePreparationError("发布提交必须是已合并的 origin/main")
    pulls = json.loads(run([GH, "api", f"repos/{REPOSITORY}/commits/{head}/pulls"], repo))
    merged = [pull for pull in pulls if pull.get("merged_at") and pull.get("merge_commit_sha") == head]
    if len(merged) != 1:
        raise ReleasePreparationError("未找到该提交对应的唯一已合并 PR")
    checks = json.loads(run([GH, "pr", "view", str(merged[0]["number"]), "--repo", REPOSITORY,
        "--json", "statusCheckRollup"], repo))["statusCheckRollup"]
    require_release_checks(checks)
    return head


def require_draft_assets(output: Path, assets: list[dict], files: list[Path] | None = None) -> None:
    files = files if files is not None else [item for item in output.iterdir() if item.is_file()]
    expected = {item.name: item for item in files}
    if len(assets) != len(expected) or {item.get("name") for item in assets} != set(expected):
        raise ReleasePreparationError("草稿附件缺失、重复或存在额外附件")
    for item in assets:
        local = expected[item["name"]]
        if item.get("size") != local.stat().st_size or item.get("digest") != "sha256:" + hashlib.sha256(local.read_bytes()).hexdigest():
            raise ReleasePreparationError("草稿附件大小或 SHA-256 与本地产物不符")


def create_release_draft(repo: Path, tag: str, sha: str, files: list[Path], notes: Path, run=run_command) -> None:
    run([GH, "release", "create", tag, *map(str, files), "--repo", REPOSITORY,
        "--draft", "--target", sha, "--title", f"AI Usage {tag[1:]}", "--notes-file", str(notes)], repo)


def prepare_release(repo: Path, output: Path, key: Path, app: Path, minimum: str, run=run_command) -> dict:
    run([GIT, "fetch", "origin"], repo)
    sha = check_release_source(repo, run)
    app_version = (repo / "clients/macos/VERSION").read_text().strip()
    tag = "v" + app_version
    if run([GIT, "ls-remote", "--tags", "origin", "refs/tags/" + tag], repo).strip():
        raise ReleasePreparationError("正式或草稿标签已存在；不覆盖标签与发布资产")
    if output.exists() and any(output.iterdir()):
        raise ReleasePreparationError("产物输出目录必须为空，避免混入旧包")
    output.mkdir(parents=True, exist_ok=True)
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"
    run([sys.executable, str(repo / "scripts/build_signed_release.py"), "--output", str(output),
        "--artifact-base-url", base, "--minimum-collector-version", minimum, "--signing-key", str(key),
        "--mac-app", str(app)], repo)
    sys.path.insert(0, str(repo / "src"))
    from ai_usage_widget.release_trust import RELEASE_PUBLIC_KEYS
    from ai_usage_widget.signed_release import extract_artifact, verify_manifest
    from ai_usage_widget.upgrade import preflight
    manifest_file = output / "release-manifest.json"
    raw_manifest = manifest_file.read_bytes()
    manifest = verify_manifest(raw_manifest, RELEASE_PUBLIC_KEYS, "stable", minimum, check_only=True)
    if manifest["app_version"] != app_version or manifest["build_sha"] != sha or set(manifest["artifacts"]) != {"linux-source", "darwin-arm64-app"}:
        raise ReleasePreparationError("签名清单与本轮提交或平台范围不一致")
    files = [manifest_file]
    with tempfile.TemporaryDirectory(prefix="aiusage-release-selfcheck-") as folder:
        temporary = Path(folder)
        for kind, artifact in manifest["artifacts"].items():
            filename = Path(urlsplit(artifact["url"]).path).name
            local = output / filename
            candidate = temporary / kind
            extract_artifact(local.read_bytes(), artifact, candidate, allow_symlinks=kind.startswith("darwin"))
            preflight(candidate, manifest, kind)
            files.append(local)
        notes = output / "release-notes.md"
        notes.write_text(f"App {app_version} / collector {manifest['collector_version']}\n\n源码：{sha}\n\n"
            "平台：macOS arm64、Linux 源码包。\n\n本草稿已完成签名、哈希、安全解包及入口预检；"
            "正式发布前仍须核对用户变化、服务端依赖、回滚和关联 Issue。\n")
        create_release_draft(repo, tag, sha, files, notes, run)
        remote = json.loads(run([GH, "release", "view", tag, "--repo", REPOSITORY, "--json", "isDraft,assets,url"], repo))
        if remote.get("isDraft") is not True:
            raise ReleasePreparationError("远端发布不是草稿，停止进一步操作")
        require_draft_assets(output, remote["assets"], files)
        downloaded = temporary / "downloaded"
        downloaded.mkdir()
        for item in files:
            run([GH, "release", "download", tag, "--repo", REPOSITORY, "--pattern", item.name,
                "--dir", str(downloaded)], repo)
            if (downloaded / item.name).read_bytes() != item.read_bytes():
                raise ReleasePreparationError("下载回读与签名产物不一致")
        verify_manifest((downloaded / manifest_file.name).read_bytes(), RELEASE_PUBLIC_KEYS, "stable", minimum, check_only=True)
    return {"status": "draft_verified", "url": remote["url"], "tag": tag, "app_version": app_version,
        "collector_version": manifest["collector_version"], "build_sha": sha, "assets_checked": len(files)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--signing-key", required=True, type=Path)
    parser.add_argument("--mac-app", required=True, type=Path)
    parser.add_argument("--minimum-collector-version", default="0.3.0")
    args = parser.parse_args()
    try:
        result = prepare_release(Path(__file__).resolve().parents[1], args.output.resolve(),
            args.signing_key.expanduser().resolve(), args.mac_app.resolve(), args.minimum_collector_version)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        print("草稿准备失败：检查干净提交、CI、签名、产物或网络；不会自动转正式", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
