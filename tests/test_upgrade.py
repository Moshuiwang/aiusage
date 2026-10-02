import json
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from ai_usage_widget.upgrade import stage_release, preflight, discover
from ai_usage_widget.signed_release import UpgradeError
from ai_usage_widget.upgrade_apply import apply_linux, apply_mac, populate_release_environment
from ai_usage_widget.deploy_release import ReleasePlan, install_release
from ai_usage_widget.deploy_units import CollectorUnitSpec
import sys


class UpgradeTests(unittest.TestCase):
    def artifact(self):
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w:gz') as archive:
            item=tarfile.TarInfo('src/file');data=b'candidate';item.size=len(data);archive.addfile(item,io.BytesIO(data))
        data=raw.getvalue()
        manifest={'collector_version':'0.5.0','app_version':'2.2.0','build_sha':'a'*40,'artifacts':{'linux-source':{'url':'https://example.test/release.tar.gz','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}
        return data,manifest
    def test_failed_probe_never_leaves_a_ready_release(self):
        data,manifest=self.artifact()
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/'ready'
            def broken(*args):raise UpgradeError('broken')
            with self.assertRaises(UpgradeError):stage_release(manifest,'linux-source',dest,fetch=lambda *args:data,probe=broken)
            self.assertFalse(dest.exists())
            calls=[]
            result=stage_release(manifest,'linux-source',dest,fetch=lambda *args:data,probe=lambda *args:calls.append(args))
            self.assertEqual(len(calls),1);self.assertEqual(result['status'],'verified')
            self.assertEqual((dest/'src/file').read_bytes(),b'candidate')
            self.assertTrue((dest/'verified-release.json').is_file())
    def test_version_module_alone_does_not_prove_cli_can_load(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder);module=stage/'src/ai_usage_widget';module.mkdir(parents=True)
            (module/'__init__.py').write_text('')
            (module/'version_contract.py').write_text('COLLECTOR_VERSION="0.5.0"')
            (module/'cli.py').write_text('this is invalid python!')
            with self.assertRaises(UpgradeError):preflight(stage,{'collector_version':'0.5.0'},'linux-source')
    def test_unconfigured_trust_never_contacts_network(self):
        calls=[]
        with self.assertRaises(UpgradeError):discover('https://example.test/update',trusted_keys={},fetch=lambda *args:calls.append(args))
        self.assertEqual(calls,[])

    def test_linux_failed_health_rolls_back_and_preserves_identity_credentials_and_outbox(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'root'; units=Path(folder)/'units'; source=Path(folder)/'source'
            package=source/'ai_usage_widget';package.mkdir(parents=True)
            (package/'__init__.py').write_text('');(package/'cli.py').write_text('')
            (root/'secrets').mkdir(parents=True);(root/'secrets/ingest.env').write_text('AI_USAGE_INGEST_TOKEN=test\n')
            spec=CollectorUnitSpec(source_id='linux-alice',release_dir=str(root/'current'),config_path=str(root/'config/device.json'),env_file=str(root/'secrets/ingest.env'),lock_file=str(root/'run/pusher.lock'),python_executable=sys.executable)
            config={'source_id':'linux-alice','server_url':'https://example.test/ingest','timezone':'Asia/Shanghai','platform':'linux'}
            installed=install_release(ReleasePlan(root,units,source,'0.3.0','b'*40,spec,device_config=config),command_runner=lambda args:0)
            self.assertTrue(installed['success'])
            stage=Path(folder)/'stage';(stage/'src').mkdir(parents=True)
            import shutil
            shutil.copytree(source/'ai_usage_widget',stage/'src/ai_usage_widget')
            outbox=root/'outbox.sqlite';outbox.write_bytes(b'persisted queue')
            before=(root/'config/device.json').read_bytes();credential=(root/'secrets/ingest.env').read_bytes()
            manifest={'collector_version':'0.4.0','build_sha':'a'*40,'min_collector_version':'0.3.0'}
            commands=[]
            result=apply_linux(root,units,stage,manifest,runner=lambda args:commands.append(args) or 0,health=lambda *args:False)
            self.assertFalse(result['success']);self.assertTrue(result['rolled_back'])
            self.assertEqual((root/'current').resolve().name,'0.3.0')
            self.assertEqual((root/'config/device.json').read_bytes(),before)
            self.assertEqual((root/'secrets/ingest.env').read_bytes(),credential)
            self.assertEqual(outbox.read_bytes(),b'persisted queue')
            self.assertGreaterEqual(len(commands),4)

    def test_mac_health_reads_nonempty_mobile_owner_sources(self):
        from ai_usage_widget.upgrade_apply import mac_health
        from ai_usage_widget.mac_app_collector import write_status
        import shutil
        fixture = Path(__file__).parent / 'fixtures/verify_cloud/healthy/mobile_summary.json'
        summary = json.loads(fixture.read_text())
        self.assertGreater(len(summary['sources']), 0)
        self.assertNotIn('source_status', summary)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'summaries').mkdir()
            cache = root / 'summaries/today-offset0.json'
            shutil.copyfile(fixture, cache)
            write_status(root, {'usage': {'success': True}, 'limits': {'success': True}})
            with patch('ai_usage_widget.upgrade_apply.time.monotonic', side_effect=[0, 0, 500]), patch('ai_usage_widget.upgrade_apply.time.sleep'):
                self.assertTrue(mac_health(root, {'collector_version': '0.4.0'}, 0))
            summary['sources'] = []
            cache.write_text(json.dumps(summary))
            with patch('ai_usage_widget.upgrade_apply.time.monotonic', side_effect=[0, 0, 500]), patch('ai_usage_widget.upgrade_apply.time.sleep'):
                self.assertFalse(mac_health(root, {'collector_version': '0.4.0'}, 0))

    def test_mac_failed_health_restores_app_and_keeps_runtime_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'runtime';root.mkdir()
            (root/'config.json').write_text('{"token":"device-secret","source_id":"stable"}')
            app=Path(folder)/'AI Usage Menu Bar.app';app.mkdir();(app/'version').write_text('old')
            stage=Path(folder)/'candidate';new=stage/'AI Usage Menu Bar.app';new.mkdir(parents=True);(new/'version').write_text('new')
            manifest={'app_version':'2.1.0','collector_version':'0.4.0','build_sha':'a'*40}
            events=[]
            result=apply_mac(root,app,stage,manifest,stop_app=lambda:events.append('stop'),launch=lambda path:events.append('launch') or True,health=lambda *args:False)
            self.assertFalse(result['success']);self.assertTrue(result['rolled_back'])
            self.assertEqual((app/'version').read_text(),'old')
            self.assertEqual(json.loads((root/'config.json').read_text())['token'],'device-secret')
            self.assertEqual(events,['stop','launch','stop','launch'])

    def test_second_mac_upgrade_keeps_one_previous_app_without_manual_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'runtime';app=Path(folder)/'AI Usage Menu Bar.app';app.mkdir();(app/'version').write_text('old')
            stage=Path(folder)/'candidate';new=stage/'AI Usage Menu Bar.app';new.mkdir(parents=True);(new/'version').write_text('new')
            manifest={'app_version':'2.1.0','collector_version':'0.4.0','build_sha':'a'*40}
            for value in ('new','newer'):
                (new/'version').write_text(value)
                result=apply_mac(root,app,stage,manifest,stop_app=lambda:None,launch=lambda path:True,health=lambda *args:True)
                self.assertTrue(result['success'])
            self.assertEqual((app/'version').read_text(),'newer')
            self.assertEqual((Path(str(app)+'.previous')/'version').read_text(),'new')
            self.assertEqual(len(list(Path(folder).glob('.aiusage-older-*'))),0)

    def test_persistent_upgrade_receipt_is_loaded_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'current').mkdir();(root/'config').mkdir()
            (root/'current/release.json').write_text(json.dumps({'revision':'a'*40}))
            history={'status':'rolled_back','from_version':'0.3.0','to_version':'0.4.0','finished_at':'2026-10-02T00:00:00Z'}
            (root/'last-upgrade.json').write_text(json.dumps(history))
            env={}
            populate_release_environment(root/'config/device.json',environment=env)
            self.assertEqual(env['AI_USAGE_BUILD_SHA'],'a'*40)
            self.assertEqual(env['AI_USAGE_LAST_UPGRADE_STATUS'],'rolled_back')
            self.assertEqual(env['AI_USAGE_LAST_UPGRADE_FROM_VERSION'],'0.3.0')
            self.assertEqual(len(env),5)
            (root/'last-upgrade.json').write_text('{"status":"secret-token"}')
            populate_release_environment(root/'config/device.json',environment=env)
            self.assertNotIn('AI_USAGE_LAST_UPGRADE_STATUS',env)
