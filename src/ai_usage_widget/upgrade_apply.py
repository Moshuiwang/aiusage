"""Apply only an already verified candidate; preserve user configuration and buffered data."""
from __future__ import annotations

from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import shlex
import subprocess
import shutil
import signal
import time
import uuid

from .deploy_release import ReleasePlan, install_release, rollback_release, read_manifest, default_command_runner
from .deploy_units import CollectorUnitSpec
from .device_enrollment import private_write
from .lock import FileLock
from .signed_release import UpgradeError, version


def populate_release_environment(config_path, *, environment=None):
    from .version_contract import local_collector_release, VersionContractError
    environment=os.environ if environment is None else environment
    config_path=Path(config_path)
    if config_path.name!='device.json' or config_path.parent.name not in ('config','collector'):return
    root=config_path.parent.parent
    def small_json(path):
        if path.stat().st_size>4096:raise ValueError()
        value=json.loads(path.read_text())
        if not isinstance(value,dict):raise ValueError()
        return value
    try:
        release=small_json(root/'current/release.json')
        local_collector_release(build_sha=release['revision'])
        environment['AI_USAGE_BUILD_SHA']=release['revision']
    except (OSError,ValueError,KeyError,VersionContractError):pass
    history_path=root/'last-upgrade.json'
    if not history_path.exists():return
    variables={'status':'AI_USAGE_LAST_UPGRADE_STATUS','from_version':'AI_USAGE_LAST_UPGRADE_FROM_VERSION',
               'to_version':'AI_USAGE_LAST_UPGRADE_TO_VERSION','finished_at':'AI_USAGE_LAST_UPGRADE_FINISHED_AT'}
    for name in variables.values():environment.pop(name,None)
    try:
        history=small_json(history_path)
        local_collector_release(last_upgrade=history)
        for key,name in variables.items():
            if key in history:environment[name]=history[key]
    except (OSError,ValueError,KeyError,VersionContractError):pass


def linux_health(spec, target):
    config=json.loads(Path(spec.config_path).read_text())
    if config.get('os_user') not in (None,getpass.getuser()):
        raise UpgradeError('必须在采集器所属的 OS 用户下升级')
    environment=dict(os.environ)
    secret=Path(spec.env_file)
    if secret.stat().st_uid!=os.getuid() or secret.stat().st_mode&0o077:
        raise UpgradeError('凭据文件必须仅属于当前用户且权限为 600')
    for line in secret.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if line.startswith('export '):line=line[7:]
        key,separator,value=line.partition('=')
        if not separator or not key.replace('_','a').isalnum():raise UpgradeError('凭据环境文件格式无效')
        values=shlex.split(value)
        if len(values)!=1:raise UpgradeError('凭据环境文件格式无效')
        environment[key]=values[0]
    environment['PYTHONPATH']=spec.python_path
    result=subprocess.run(spec.exec_argv(),cwd=spec.release_dir,env=environment,capture_output=True,text=True,timeout=240)
    if result.returncode:return False
    try:
        report=json.loads(result.stdout)
        return report.get('success') is True and report.get('collection_status','ok')=='ok'
    except (ValueError,AttributeError):return False


def apply_linux(root, unit_dir, stage, manifest, *, runner=default_command_runner, health=linux_health):
    root=Path(root);unit_dir=Path(unit_dir);stage=Path(stage)
    (root/'run').mkdir(parents=True,exist_ok=True)
    with FileLock(str(root/'run/upgrade.lock')):
        old=read_manifest(root/'current')
        if not old:raise UpgradeError('请先安装带版本记录的采集器')
        if old['timer_scope']!='user':raise UpgradeError('system 级部署需要所属用户与 Ops 协调升级')
        if not version(manifest['min_collector_version'])<=version(old['version'])<version(manifest['collector_version']):raise UpgradeError('当前安装版本不在允许升级范围')
        spec=CollectorUnitSpec(**old['unit_spec'])
        manager=['systemctl','--user']
        if runner(manager+['stop',spec.timer_name,spec.service_name]):
            runner(manager+['enable','--now',spec.timer_name])
            raise UpgradeError('无法暂停原采集任务；未切换版本')
        result=None
        try:
            plan=ReleasePlan(root,unit_dir,stage/'src',manifest['collector_version'],manifest['build_sha'],spec,
                             activation_commands=[manager+['daemon-reload']],timer_scope='user')
            result=install_release(plan,command_runner=runner)
            if result['success']:
                try:healthy=health(spec,manifest['collector_version'])
                except Exception:healthy=False
                if not healthy:
                    result.update(success=False,rolled_back=False,health_verified=False)
                    try:
                        rollback=rollback_release(root,unit_dir,command_runner=runner)
                        result['rolled_back']=rollback['success']
                    except Exception:
                        result['rollback_failed']=True
                else:result['health_verified']=True
            return result
        finally:
            resumed=runner(manager+['enable','--now',spec.timer_name])==0
            if result is not None:
                if not resumed:result.update(success=False,timer_resumed=False)
                status='succeeded' if result['success'] else 'rolled_back' if result.get('rolled_back') else 'failed'
                private_write(root/'last-upgrade.json',json.dumps({'status':status,'from_version':old['version'],
                              'to_version':manifest['collector_version'],'finished_at':datetime.now(timezone.utc).isoformat()}))


def stop_mac_app(app):
    executable=str(Path(app).resolve()/'Contents/MacOS/AIUsageMenuBar')
    def pids():
        output=subprocess.run(['ps','-ww','-axo','pid=,uid=,comm='],capture_output=True,text=True,check=True).stdout
        found=[]
        for line in output.splitlines():
            fields=line.strip().split(None,2)
            if len(fields)==3 and fields[1]==str(os.getuid()) and fields[2]==executable:found.append(int(fields[0]))
        return found
    current=pids()
    for pid in current:os.kill(pid,signal.SIGTERM)
    deadline=time.monotonic()+20
    while pids():
        if time.monotonic()>deadline:raise UpgradeError('App 未退出；未替换版本')
        time.sleep(0.5)


def launch_mac_app(app):
    return subprocess.run(['open',str(app)],capture_output=True,timeout=15).returncode==0


def wait_mac_collector(root):
    import fcntl
    path=Path(root)/'collector/daemon.lock'
    if not path.exists():return
    deadline=time.monotonic()+20
    with path.open('a') as handle:
        while True:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(handle,fcntl.LOCK_UN)
                return
            except BlockingIOError:
                if time.monotonic()>deadline:raise UpgradeError('原采集器尚未停止；未替换版本')
                time.sleep(0.5)


def mac_health(root, manifest, started):
    root=Path(root);deadline=time.monotonic()+480
    status_path=root/'collector/status.json';cache=root/'summaries/today-offset0.json'
    while time.monotonic()<deadline:
        try:
            if status_path.stat().st_mtime>started:
                status=json.loads(status_path.read_text())
                if status.get('collector_version')==manifest['collector_version']:
                    jobs=[status.get(name,{}) for name in ('usage','limits')]
                    if any(job.get('success') is False for job in jobs):return False
                    if all(job.get('success') is True for job in jobs) and cache.stat().st_mtime>started:
                        summary=json.loads(cache.read_text())
                        if isinstance(summary.get('sources'), list) and summary['sources']:return True
        except (OSError,ValueError):pass
        time.sleep(1)
    return False


def apply_mac(root, app, stage, manifest, *, stop_app=None, launch=launch_mac_app, health=mac_health):
    root=Path(root);app=Path(app);stage=Path(stage)
    root.mkdir(parents=True,exist_ok=True)
    stop_app=stop_app or (lambda:stop_mac_app(app))
    backup=app.with_name(app.name+'.previous')
    candidate=app.with_name('.aiusage-candidate-'+uuid.uuid4().hex+'.app')
    older=app.with_name('.aiusage-older-'+uuid.uuid4().hex+'.app')
    with FileLock(str(root/'upgrade.lock')):
        if not app.is_dir():raise UpgradeError('找不到已安装的 Mac App')
        shutil.copytree(stage/'AI Usage Menu Bar.app',candidate,symlinks=True)
        switched=False
        try:
            stop_app();wait_mac_collector(root)
            if backup.exists():backup.rename(older)
            app.rename(backup)
            try:candidate.rename(app)
            except Exception:
                backup.rename(app)
                if older.exists():older.rename(backup)
                launch(app);raise
            switched=True;started=time.time()
            try:healthy=launch(app) and health(root,manifest,started)
            except Exception:healthy=False
            if not healthy:
                stop_app();wait_mac_collector(root)
                failed=app.with_name('.aiusage-failed-'+uuid.uuid4().hex+'.app')
                app.rename(failed);backup.rename(app)
                if older.exists():older.rename(backup)
                restored=launch(app)
                shutil.rmtree(failed)
                private_write(root/'last-upgrade.json',json.dumps({'status':'rolled_back' if restored else 'failed',
                              'to_version':manifest['collector_version'],'finished_at':datetime.now(timezone.utc).isoformat()}))
                return {'success':False,'rolled_back':restored,'health_verified':False}
            private_write(root/'last-upgrade.json',json.dumps({'status':'succeeded','to_version':manifest['collector_version'],
                          'finished_at':datetime.now(timezone.utc).isoformat()}))
            if older.exists():shutil.rmtree(older)
            return {'success':True,'health_verified':True,'previous_app':str(backup)}
        finally:
            if candidate.exists():shutil.rmtree(candidate)
            if not switched and app.exists():launch(app)
