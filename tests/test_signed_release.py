import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from ai_usage_widget.signed_release import verify_manifest, extract_artifact, UpgradeError


class SignedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        public=self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.keys={'test':base64.b64encode(public).decode()}
        self.manifest={'schema_version':1,'collector_version':'0.4.0','app_version':'2.1.0','channel':'stable','build_sha':'a'*40,
                       'published_at':'2026-10-02T00:00:00Z','min_collector_version':'0.3.0',
                       'artifacts':{'linux-source':{'url':'https://example.test/linux.tar.gz','sha256':'b'*64,'size':100}}}
    def envelope(self,manifest=None):
        raw=json.dumps(manifest or self.manifest,separators=(',',':')).encode()
        return json.dumps({'key_id':'test','payload':base64.b64encode(raw).decode(),'signature':base64.b64encode(self.key.sign(raw)).decode()}).encode()
    def test_valid_signature_channel_and_forward_version_are_required(self):
        result=verify_manifest(self.envelope(),self.keys,'stable','0.3.0')
        self.assertEqual(result['collector_version'],'0.4.0');self.assertEqual(len(result['artifacts']),1)
        altered=json.loads(self.envelope());payload=json.loads(base64.b64decode(altered['payload']));payload['collector_version']='9.9.9'
        altered['payload']=base64.b64encode(json.dumps(payload).encode()).decode()
        with self.assertRaises(UpgradeError):verify_manifest(json.dumps(altered).encode(),self.keys,'stable','0.3.0')
        for keys,channel,current in [({},'stable','0.3.0'),(self.keys,'beta','0.3.0'),(self.keys,'stable','0.4.0'),(self.keys,'stable','0.2.0')]:
            with self.assertRaises(UpgradeError):verify_manifest(self.envelope(),keys,channel,current)
    def archive(self,name='src/ai_usage_widget/version_contract.py',kind=None,link=None):
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w:gz') as archive:
            entry=tarfile.TarInfo(name);data=b'COLLECTOR_VERSION="0.4.0"\n';entry.size=len(data)
            if kind:entry.type=kind;entry.linkname=link or '';entry.size=0
            archive.addfile(entry,io.BytesIO(data) if not kind else None)
        return raw.getvalue()
    def test_archive_hash_size_and_paths_are_checked_before_any_install(self):
        raw=self.archive()
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/'stage'
            extract_artifact(raw,{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)},dest)
            self.assertEqual((dest/'src/ai_usage_widget/version_contract.py').read_bytes(),b'COLLECTOR_VERSION="0.4.0"\n')
            with self.assertRaises(UpgradeError):extract_artifact(raw,{'sha256':'0'*64,'size':len(raw)},Path(folder)/'bad')
            self.assertFalse((Path(folder)/'bad').exists())
            for name,kind,link in [('../escape',None,None),('/escape',None,None),('link',tarfile.SYMTYPE,'../escape'),('hard',tarfile.LNKTYPE,'src/file'),('fifo',tarfile.FIFOTYPE,None)]:
                bad=self.archive(name,kind,link)
                with self.assertRaises(UpgradeError):extract_artifact(bad,{'sha256':hashlib.sha256(bad).hexdigest(),'size':len(bad)},Path(folder)/'unsafe')
    def test_app_internal_symlinks_work_but_link_chain_escape_does_not(self):
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w:gz') as archive:
            for name,target in [('App.app/Contents/Current','Versions/A'),('App.app/Contents/escape','../../../outside')]:
                item=tarfile.TarInfo(name);item.type=tarfile.SYMTYPE;item.linkname=target;archive.addfile(item)
        data=raw.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(UpgradeError):extract_artifact(data,{'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)},Path(folder)/'stage',allow_symlinks=True)
