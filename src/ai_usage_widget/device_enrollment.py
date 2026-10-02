"""Device-generated credentials: pairing never transfers an operator token to a device."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import getpass


class EnrollmentError(ValueError):
    pass


def base_url(value):
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('', '/'):
        raise EnrollmentError('服务地址必须是 HTTPS 域名，不含路径或凭据')
    return value.rstrip('/')


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_json(url, method, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=15) as response:
            raw = response.read(65537)
            if len(raw)>65536:
                raise EnrollmentError('设备注册响应过大')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise EnrollmentError('设备注册响应无效')
            return result
    except urllib.error.HTTPError as error:
        # Do not echo request body, credentials or server-provided diagnostic text.
        raise EnrollmentError('设备注册请求失败（HTTP %d）' % error.code) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise EnrollmentError('无法连接设备注册服务，请稍后手动重试') from None


def begin(server, pending_path, source_ids, read_requested, *, api=request_json):
    server = base_url(server)
    if not 1 <= len(source_ids) <= 8 or len(set(source_ids)) != len(source_ids) or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', item) for item in source_ids):
        raise EnrollmentError('来源标识无效')
    path = Path(pending_path)
    if path.exists():
        state = json.loads(path.read_text())
        if state['server'] != server or state['source_ids'] != source_ids or state['read_requested'] != read_requested:
            raise EnrollmentError('已有待处理申请，请先处理或删除本机申请文件')
    else:
        state = {'server':server, 'source_ids':source_ids, 'read_requested':read_requested,
                 'credential':'dvc_'+secrets.token_hex(32), 'request_secret':secrets.token_hex(32),
                 'machine':platform.node(), 'os_user':getpass.getuser(), 'platform':platform.system().lower()}
        if state['platform'] not in ('darwin','linux'):
            raise EnrollmentError('当前仅支持 macOS 和 Linux')
        # Persist before sending so interrupted registration can be retried without losing the credential.
        private_write(path, json.dumps(state))
    body = {key:state[key] for key in ('source_ids','read_requested','machine','os_user','platform')}
    body['credential_hash'] = hashlib.sha256(state['credential'].encode()).hexdigest()
    body['request_secret_hash'] = hashlib.sha256(state['request_secret'].encode()).hexdigest()
    result = api(server+'/api/devices/enrollments','POST',body)
    for key in ('request_id','user_code','expires_at'):
        if not isinstance(result.get(key),str) or not result[key]:
            raise EnrollmentError('设备申请响应缺少 '+key)
        state[key] = result[key]
    private_write(path, json.dumps(state))
    return {key:state[key] for key in ('request_id','user_code','expires_at','source_ids','read_requested')}


def finish(pending_path, *, token_env_file=None, token_env='AI_USAGE_INGEST_TOKEN', display_config=None, api=request_json):
    if bool(token_env_file) == bool(display_config):
        raise EnrollmentError('请指定 Linux 凭据文件或 Mac 应用配置中的一个')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',token_env):
        raise EnrollmentError('环境变量名无效')
    path=Path(pending_path)
    state=json.loads(path.read_text())
    server=base_url(state['server'])
    # Self is authoritative after approval, even when the short-lived pairing request has expired.
    try:
        identity=api(server+'/api/devices/self','GET',None,state['credential'])
    except EnrollmentError:
        identity=api(server+'/api/devices/enrollments/'+state['request_id']+'/status','POST',{'request_secret':state['request_secret']})
        return {'status':identity['status'],'request_id':state['request_id']}
    if identity.get('status') != 'approved':
        return {'status':identity.get('status','unknown'),'request_id':state['request_id']}
    if set(identity.get('source_ids',[])) != set(state['source_ids']) or identity.get('read_allowed') != state['read_requested']:
        raise EnrollmentError('批准的来源或读取权限与本机申请不一致')
    if display_config:
        if not identity['read_allowed']:
            raise EnrollmentError('Mac 呈现端需要申请读取权限')
        target=Path(display_config)
        config=json.loads(target.read_text()) if target.exists() else {}
        if config.get('server_url') and base_url(config['server_url']) != server:
            raise EnrollmentError('应用服务地址与批准的设备不一致')
        config.update(server_url=server,token=state['credential'])
        private_write(target,json.dumps(config,ensure_ascii=False))
    else:
        private_write(token_env_file,token_env+'='+state['credential']+'\n')
    path.unlink()
    return {'status':'activated','request_id':state['request_id'],'source_ids':state['source_ids']}


def register_parser(subparsers):
    parser=subparsers.add_parser('devices',help='设备申请、批准和撤销；不通过 SSH 传递共享 token')
    actions=parser.add_subparsers(dest='device_action',required=True)
    enroll=actions.add_parser('enroll'); enroll.add_argument('--server',required=True)
    enroll.add_argument('--source-id',action='append',required=True,dest='source_ids')
    enroll.add_argument('--read',action='store_true',dest='read_requested')
    enroll.add_argument('--pending',default=str(Path.home()/'.config/ai-usage/enrollment.json'))
    check=actions.add_parser('check');check.add_argument('--pending',default=str(Path.home()/'.config/ai-usage/enrollment.json'))
    output=check.add_mutually_exclusive_group(required=True)
    output.add_argument('--token-env-file');output.add_argument('--display-config')
    check.add_argument('--token-env',default='AI_USAGE_INGEST_TOKEN')
    for action in ('list','approve','deny','revoke'):
        command=actions.add_parser(action);command.add_argument('--server',required=True)
        command.add_argument('--token-env',default='AI_USAGE_DEVICE_ADMIN_TOKEN')
        if action != 'list':command.add_argument('--request-id',required=True)
        if action=='approve':command.add_argument('--read',action='store_true')


def run(args):
    try:
        if args.device_action=='enroll':
            result=begin(args.server,Path(args.pending).expanduser(),args.source_ids,args.read_requested)
        elif args.device_action=='check':
            result=finish(Path(args.pending).expanduser(),token_env_file=Path(args.token_env_file).expanduser() if args.token_env_file else None,
                          token_env=args.token_env,display_config=Path(args.display_config).expanduser() if args.display_config else None)
        else:
            token=os.environ.get(args.token_env)
            if not token:raise EnrollmentError('管理员凭据环境变量未配置')
            server=base_url(args.server)
            if args.device_action=='list':
                result=request_json(server+'/api/devices/enrollments','GET',token=token)
            else:
                if not re.fullmatch(r'[a-f0-9-]{36}',args.request_id):raise EnrollmentError('申请 ID 无效')
                prefix='/api/devices/' if args.device_action=='revoke' else '/api/devices/enrollments/'
                result=request_json(server+prefix+args.request_id+'/'+args.device_action,'POST',
                                    {'read_allowed':args.read} if args.device_action=='approve' else {},token)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (EnrollmentError,OSError,KeyError,ValueError):
        print(json.dumps({'status':'error','message':'设备操作失败；检查服务是否升级、批准状态和本机配置'},ensure_ascii=False));return 2
