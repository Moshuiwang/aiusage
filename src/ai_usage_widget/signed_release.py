"""Verify a signed release before exposing any artifact to an installer."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.parse
import urllib.request

MAX_ARTIFACT=200*1024*1024
MAX_EXPANDED=512*1024*1024


class UpgradeError(ValueError):
    def __init__(self, message, *, error_type='verification_failed'):
        super().__init__(message)
        self.error_type = error_type


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value):
        raise UpgradeError('发布版本格式无效')
    return tuple(map(int,value.split('.')))


def public_url(value):
    parts=urllib.parse.urlsplit(value)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise UpgradeError('发布产物必须使用 HTTPS 地址')
    return value


def verify_manifest(raw, trusted_keys, channel, current_collector, *, current_app=None, check_only=False):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        if len(raw)>32768:raise ValueError()
        envelope=json.loads(raw)
        if set(envelope)!= {'key_id','payload','signature'}:raise ValueError()
        key=base64.b64decode(trusted_keys[envelope['key_id']],validate=True)
        payload=base64.b64decode(envelope['payload'],validate=True)
        signature=base64.b64decode(envelope['signature'],validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(signature,payload)
        manifest=json.loads(payload)
        if set(manifest)!= {'schema_version','collector_version','app_version','channel','build_sha','published_at','min_collector_version','artifacts'}:raise ValueError()
        if manifest['schema_version']!=1 or manifest['channel']!=channel or channel not in ('stable','beta','dev'):raise ValueError()
        target=version(manifest['collector_version']); minimum=version(manifest['min_collector_version']); app=version(manifest['app_version']); current=version(current_collector)
        if current<minimum or minimum>target:raise ValueError()
        if not check_only:
            if target<current:raise ValueError()
            if current_app is None:
                if target<=current:raise ValueError()
            elif app<=version(current_app):raise ValueError()
        if not re.fullmatch(r'[a-f0-9]{40,64}',manifest['build_sha']):raise ValueError()
        published=datetime.fromisoformat(manifest['published_at'].replace('Z','+00:00'))
        if published.tzinfo is None or published>datetime.now(timezone.utc):raise ValueError()
        artifacts=manifest['artifacts']
        if not isinstance(artifacts,dict) or not artifacts or set(artifacts)-{'linux-source','darwin-arm64-app','darwin-x86_64-app'}:raise ValueError()
        for item in artifacts.values():
            if set(item)!= {'url','sha256','size'} or not re.fullmatch(r'[a-f0-9]{64}',item['sha256']):raise ValueError()
            if type(item['size']) is not int or not 0<item['size']<=MAX_ARTIFACT:raise ValueError()
            public_url(item['url'])
        return manifest
    except Exception as error:
        raise UpgradeError('发布清单验签或版本校验失败；保持当前版本') from None


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        return super().redirect_request(request,fp,code,message,headers,newurl)


def download(url, limit):
    public_url(url)
    try:
        with urllib.request.build_opener(HTTPSRedirect()).open(url,timeout=30) as response:
            raw=response.read(limit+1)
            if len(raw)>limit:raise UpgradeError('发布下载超过大小限制')
            return raw
    except UpgradeError:raise
    except Exception:raise UpgradeError('无法下载发布产物；保持当前版本', error_type='download_failed') from None


def extract_artifact(raw, artifact, destination, *, allow_symlinks=False):
    if len(raw)!=artifact['size'] or len(raw)>MAX_ARTIFACT or hashlib.sha256(raw).hexdigest()!=artifact['sha256']:
        raise UpgradeError('发布产物大小或校验和不匹配')
    destination=Path(destination)
    if destination.exists():raise UpgradeError('升级临时目录必须为空')
    root=destination.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            members=[]; expanded=0
            for item in archive:
                expanded+=item.size
                if len(members)>=10000 or expanded>MAX_EXPANDED:raise UpgradeError('发布包展开大小超限')
                members.append(item)
            if not members:raise UpgradeError('发布包为空')
            names=set(); links=[]
            for item in members:
                path=PurePosixPath(item.name)
                if path.is_absolute() or '..' in path.parts or not path.parts or item.name in names:raise UpgradeError('发布包路径无效')
                names.add(item.name)
                if item.issym() and allow_symlinks:
                    target=PurePosixPath(item.linkname)
                    resolved=(root/item.name).parent.joinpath(item.linkname).resolve()
                    if target.is_absolute() or not resolved.is_relative_to(root):raise UpgradeError('发布包符号链接越界')
                    links.append(item)
                elif not (item.isfile() or item.isdir()):raise UpgradeError('发布包含不支持的文件类型')
            # No regular file may be placed below a symlink, regardless of archive order.
            for item in members:
                if any(PurePosixPath(link.name) in PurePosixPath(item.name).parents for link in links):raise UpgradeError('发布包文件位于符号链接下')
            destination.mkdir(mode=0o700,parents=True)
            for item in members:
                target=root/item.name
                if item.isdir():target.mkdir(parents=True,exist_ok=True)
                elif item.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(item) as source,target.open('xb') as output:
                        while chunk:=source.read(1024*1024):output.write(chunk)
                    target.chmod(0o755 if item.mode&0o111 else 0o644)
            for item in links:
                target=root/item.name;target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(item.linkname)
            for item in links:
                if not (root/item.name).resolve().is_relative_to(root):raise UpgradeError('发布包链接链越界')
    except UpgradeError:raise
    except (OSError,tarfile.TarError,ValueError):raise UpgradeError('发布包无法安全展开') from None
