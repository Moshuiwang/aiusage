"""Shared signed update discovery and isolated preflight for Linux and the unified Mac App."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile

from .release_trust import RELEASE_PUBLIC_KEYS, UPDATE_MANIFEST_URL
from .signed_release import UpgradeError, download, extract_artifact, verify_manifest
from .version_contract import COLLECTOR_VERSION


def discover(url=None, *, channel='stable', current_app=None, trusted_keys=None, fetch=download):
    keys=RELEASE_PUBLIC_KEYS if trusted_keys is None else trusted_keys
    if not keys or not (url or UPDATE_MANIFEST_URL):
        raise UpgradeError('更新服务尚未配置签名公钥与发布地址，请管理员先完成签名发布')
    return verify_manifest(fetch(url or UPDATE_MANIFEST_URL,32768),keys,channel,COLLECTOR_VERSION,current_app=current_app)


def preflight(stage, manifest, artifact_id, *, python=sys.executable, run=subprocess.run):
    stage=Path(stage)
    if artifact_id=='linux-source':
        module=stage/'src/ai_usage_widget/version_contract.py'
        if not module.is_file() or not (stage/'src/ai_usage_widget/cli.py').is_file():raise UpgradeError('Linux 发布包缺少采集器入口')
        # Isolated import does not accidentally read the currently running source tree.
        code='import sys;sys.path.insert(0,'+repr(str(stage/'src'))+');from ai_usage_widget.cli import main;main(["--version"])'
        argv=[python,'-I','-c',code]
    else:
        app=stage/'AI Usage Menu Bar.app'
        info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleShortVersionString')!=manifest['app_version'] or info.get('CFBundleIdentifier')!='com.chunbai.aiusage.menubar.app' or info.get('AIUsageBuildSHA')!=manifest['build_sha']:raise UpgradeError('Mac App 版本或标识与签名发布不一致')
        if run(['codesign','--verify','--deep','--strict',str(app)],capture_output=True,timeout=30).returncode:raise UpgradeError('Mac App 签名完整性校验失败')
        helper=app/'Contents/Helpers/AIUsageCollector.app/Contents/MacOS/AIUsageCollector'
        argv=[str(helper),'--collector-cli','--version']
    try:
        result=run(argv,capture_output=True,text=True,timeout=30,env={**os.environ,'PYTHONPATH':''})
        if result.returncode or result.stdout.strip()!=manifest['collector_version']:raise UpgradeError('候选采集器版本自报与签名发布不一致')
    except (OSError,subprocess.TimeoutExpired):raise UpgradeError('候选采集器无法启动；保持当前版本') from None


def stage_release(manifest, artifact_id, destination, *, fetch=download, probe=preflight):
    try:artifact=manifest['artifacts'][artifact_id]
    except KeyError:raise UpgradeError('本次发布未包含当前平台产物') from None
    destination=Path(destination)
    if destination.exists():raise UpgradeError('升级暂存目录已存在，请使用新目录')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Failed verification never leaves a directory that an installer could mistake for a ready release.
    with tempfile.TemporaryDirectory(prefix='.aiusage-update-',dir=destination.parent) as temporary:
        candidate=Path(temporary)/'candidate'
        extract_artifact(fetch(artifact['url'],artifact['size']),artifact,candidate,allow_symlinks=artifact_id.startswith('darwin-'))
        probe(candidate,manifest,artifact_id)
        (candidate/'verified-release.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        candidate.rename(destination)
    return {'status':'verified','stage':str(destination),'collector_version':manifest['collector_version'],'app_version':manifest['app_version'],'build_sha':manifest['build_sha']}


def register_parser(subparsers):
    parser=subparsers.add_parser('upgrade',help='检查签名发布并预检升级产物；不修改设备配置')
    parser.add_argument('upgrade_action',choices=['check','stage','apply'])
    parser.add_argument('--manifest-url')
    parser.add_argument('--channel',choices=['stable','beta','dev'],default='stable')
    parser.add_argument('--app-version',help='Mac App 当前版本；Linux 不填写')
    parser.add_argument('--root',help='Linux 采集器部署根目录或 Mac App 的运行配置目录')
    parser.add_argument('--app-path',help='Mac 当前 App 的绝对路径')
    parser.add_argument('--unit-dir',default=str(Path.home()/'.config/systemd/user'))
    parser.add_argument('--destination',help='已预检产物保存目录（stage 必填且必须不存在）')


def run(args):
    try:
        manifest=discover(args.manifest_url,channel=args.channel,current_app=args.app_version)
        result={'status':'update_available','collector_version':manifest['collector_version'],'app_version':manifest['app_version'],'build_sha':manifest['build_sha']}
        if args.upgrade_action=='apply':
            if not args.root:raise UpgradeError('升级需要 --root')
            from .upgrade_apply import apply_linux, apply_mac
            artifact='linux-source' if platform.system()=='Linux' else 'darwin-'+platform.machine()+'-app'
            with tempfile.TemporaryDirectory(prefix='aiusage-upgrade-') as temporary:
                stage=Path(temporary)/'candidate'
                stage_release(manifest,artifact,stage)
                if platform.system()=='Linux':
                    result=apply_linux(Path(args.root).expanduser(),Path(args.unit_dir).expanduser(),stage,manifest)
                else:
                    if not args.app_path or not args.app_version:raise UpgradeError('Mac 升级需要 App 路径与当前 App 版本')
                    result=apply_mac(Path(args.root).expanduser(),Path(args.app_path).expanduser(),stage,manifest)
        if args.upgrade_action=='stage':
            if not args.destination:raise UpgradeError('stage 需要指定暂存目录')
            artifact='linux-source' if platform.system()=='Linux' else 'darwin-'+platform.machine()+'-app'
            result=stage_release(manifest,artifact,Path(args.destination).expanduser())
        print(json.dumps(result,ensure_ascii=False));return 0 if result.get('success',True) else 1
    except Exception:
        print(json.dumps({'status':'error','message':'签名更新未就绪或校验失败；保持当前版本'},ensure_ascii=False));return 2
