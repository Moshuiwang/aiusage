#!/usr/bin/env python3
"""Build public release artifacts and sign their manifest on the release owner machine."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from ai_usage_widget.version_contract import COLLECTOR_VERSION
from ai_usage_widget.signed_release import public_url, version


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--artifact-base-url',required=True)
    parser.add_argument('--signing-key',type=Path,required=True,help='Ops-owned Ed25519 PEM key outside the repository; never printed')
    parser.add_argument('--channel',choices=['stable','beta','dev'],default='stable')
    parser.add_argument('--minimum-collector-version',required=True)
    parser.add_argument('--mac-app',type=Path)
    parser.add_argument('--mac-architecture',choices=['arm64','x86_64'],default='arm64')
    args=parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO).strip():raise ValueError('发布只能从干净的提交构建')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    key_path=args.signing_key.expanduser().resolve()
    if key_path.is_relative_to(REPO) or key_path.stat().st_uid!=os.getuid() or key_path.stat().st_mode&0o077:raise ValueError('签名私钥必须在仓库外，仅属于当前用户且权限为 600')
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key=load_pem_private_key(key_path.read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('发布签名必须使用 Ed25519')
    minimum=args.minimum_collector_version
    if version(minimum)>version(COLLECTOR_VERSION):raise ValueError('最低升级版本不能高于发布版本')
    app_version=(REPO/'clients/macos/VERSION').read_text().strip();version(app_version)
    base=public_url(args.artifact_base_url).rstrip('/')
    args.output.mkdir(parents=True,exist_ok=True)
    artifacts={}
    def record(name,filename):
        path=args.output/filename
        artifacts[name]={'url':base+'/'+filename,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    linux_name='aiusage-collector-'+COLLECTOR_VERSION+'-linux.tar.gz'
    with tarfile.open(args.output/linux_name,'w:gz') as archive:
        archive.add(REPO/'src/ai_usage_widget',arcname='src/ai_usage_widget',filter=lambda item:None if '__pycache__' in item.name or item.name.endswith('.pyc') else item)
        archive.add(REPO/'pyproject.toml',arcname='pyproject.toml')
    record('linux-source',linux_name)
    if args.mac_app:
        info=plistlib.loads((args.mac_app/'Contents/Info.plist').read_bytes())
        if info['CFBundleShortVersionString']!=app_version:raise ValueError('Mac App 版本与 VERSION 文件不一致')
        if info.get('AIUsageBuildSHA')!=sha:raise ValueError('Mac App 必须从当前发布提交重新构建')
        subprocess.run(['codesign','--verify','--deep','--strict',str(args.mac_app)],check=True,capture_output=True)
        mac_name='aiusage-'+app_version+'-macos-'+args.mac_architecture+'.tar.gz'
        with tarfile.open(args.output/mac_name,'w:gz') as archive:archive.add(args.mac_app,arcname='AI Usage Menu Bar.app')
        record('darwin-'+args.mac_architecture+'-app',mac_name)
    manifest={'schema_version':1,'collector_version':COLLECTOR_VERSION,'app_version':app_version,'channel':args.channel,
              'build_sha':sha,'published_at':datetime.now(timezone.utc).isoformat(),'min_collector_version':minimum,'artifacts':artifacts}
    payload=json.dumps(manifest,separators=(',',':'),sort_keys=True).encode()
    from cryptography.hazmat.primitives import serialization
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    key_id=hashlib.sha256(public).hexdigest()[:16]
    envelope={'key_id':key_id,'payload':base64.b64encode(payload).decode(),'signature':base64.b64encode(key.sign(payload)).decode()}
    (args.output/'release-manifest.json').write_text(json.dumps(envelope,sort_keys=True)+'\n')
    # Public key is an Ops review artifact; clients pin it in release_trust.py before publishing.
    (args.output/'release-public-key.json').write_text(json.dumps({key_id:base64.b64encode(public).decode()})+'\n')
    print(json.dumps({'collector_version':COLLECTOR_VERSION,'app_version':app_version,'artifacts':len(artifacts),'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception:
        print('发布失败：检查干净提交、产物版本、签名私钥权限与构建来源；未发布到远端',file=sys.stderr)
        raise SystemExit(1)
