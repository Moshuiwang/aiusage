import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

from ai_usage_widget.device_enrollment import begin, finish, request_json, EnrollmentError


class EnrollmentTests(unittest.TestCase):
    def test_all_device_http_methods_use_product_identity_and_preserve_authorization(self):
        captured = []
        class Opener:
            def open(self, request, timeout):
                captured.append((request, timeout))
                return io.BytesIO(b'{"status":"ok"}')
        with patch('ai_usage_widget.device_enrollment.urllib.request.build_opener', return_value=Opener()):
            for method, body, token in [('POST', {'read_requested': True}, None), ('GET', None, 'test-device'), ('POST', {}, 'test-admin')]:
                with self.subTest(method=method, token=token):
                    self.assertEqual(request_json('https://example.test/api/devices/enrollments', method, body, token), {'status':'ok'})
        self.assertEqual(len(captured), 3)
        for request, timeout in captured:
            self.assertEqual(request.get_header('User-agent'), 'AIUsagePusher/1.0')
            self.assertEqual(request.get_header('Content-type'), 'application/json')
            self.assertEqual(timeout, 15)
        self.assertIsNone(captured[0][0].get_header('Authorization'))
        self.assertEqual(json.loads(captured[0][0].data), {'read_requested':True})
        self.assertEqual(captured[1][0].get_header('Authorization'), 'Bearer test-device')
        self.assertEqual(captured[2][0].get_header('Authorization'), 'Bearer test-admin')

    def test_begin_sends_hashes_only_and_reuses_private_pending_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pending.json'
            sent = []
            def api(url, method, body, token=None):
                sent.append(body)
                return {'request_id':'request','user_code':'ABC123','expires_at':'later'}
            public = begin('https://example.test', path, ['linux-alice'], False, api=api)
            pending = json.loads(path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(pending['credential']), 68)
            self.assertEqual(len(sent[0]['credential_hash']), 64)
            self.assertNotIn(pending['credential'], json.dumps(sent) + json.dumps(public))
            self.assertNotIn(pending['request_secret'], json.dumps(sent) + json.dumps(public))
            begin('https://example.test', path, ['linux-alice'], False, api=api)
            self.assertEqual(sent[0], sent[1])
            with self.assertRaises(EnrollmentError):
                begin('https://other.test', path, ['linux-alice'], False, api=api)

    def test_only_approved_exact_scope_activates_token_and_preserves_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'pending.json'
            begin('https://example.test',path,['mac-alice'],True,api=lambda *args: {'request_id':'id','user_code':'ABC','expires_at':'later'})
            config = Path(folder)/'config.json'
            config.write_text('{"server_url":"https://example.test","timezone":"Asia/Shanghai"}')
            def pending(*args): return {'status':'pending'}
            result = finish(path, display_config=config, api=pending)
            self.assertEqual(result['status'], 'pending')
            self.assertNotIn('token',json.loads(config.read_text()))
            def wrong(*args): return {'status':'approved','source_ids':['other'],'read_allowed':True}
            with self.assertRaises(EnrollmentError): finish(path, display_config=config, api=wrong)
            def approved(*args): return {'status':'approved','source_ids':['mac-alice'],'read_allowed':True}
            result=finish(path,display_config=config,api=approved)
            data=json.loads(config.read_text())
            self.assertEqual(result['status'],'activated')
            self.assertEqual(data['timezone'],'Asia/Shanghai')
            self.assertTrue(data['token'].startswith('dvc_'))
            self.assertEqual(config.stat().st_mode & 0o777,0o600)
            self.assertFalse(path.exists())

    def test_linux_activation_writes_private_env_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'pending.json'; env=Path(folder)/'token.env'
            begin('https://example.test',path,['linux'],False,api=lambda *args: {'request_id':'id','user_code':'ABC','expires_at':'later'})
            credential=json.loads(path.read_text())['credential']
            result=finish(path,token_env_file=env,api=lambda *args: {'status':'approved','source_ids':['linux'],'read_allowed':False})
            self.assertEqual(env.read_text(),'AI_USAGE_INGEST_TOKEN='+credential+'\n')
            self.assertEqual(env.stat().st_mode & 0o777,0o600)
            self.assertNotIn(credential,json.dumps(result))
            self.assertFalse(path.exists())
