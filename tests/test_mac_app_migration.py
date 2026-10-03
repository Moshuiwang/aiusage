import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'clients/macos/scripts/install_menu_bar_app.py'
spec = importlib.util.spec_from_file_location('migration_installer', path)
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)

class MigrationTests(unittest.TestCase):
    def test_import_preserves_source_outbox_and_does_not_enable_before_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'Library/Application Support/AIUsageWidget/config'
            old.mkdir(parents=True)
            device = {'source_id':'existing-device','server_url':'https://example.test/ingest','outbox':{'enabled':True,'path':'/existing/outbox.sqlite'}}
            (old / 'device.json').write_text(json.dumps(device))
            runtime = root / 'new'
            installer.import_existing_collector(home=root, runtime_dir=runtime)
            self.assertEqual(json.loads((runtime / 'collector/device.json').read_text()),device)
            self.assertFalse((runtime / 'collector/settings.json').exists())
            self.assertEqual((runtime / 'collector/device.json').stat().st_mode & 0o777,0o600)

    def test_import_prefers_latest_limits_runtime_and_does_not_overwrite_user_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'Library/Application Support/AIUsageWidget/config'
            old.mkdir(parents=True)
            (old/'device.json').write_text('{"source_id":"old"}')
            (old/'limits.json').write_text('{"providers":[]}')
            latest = root / 'Library/Application Support/ai-usage-widget/runtime'
            latest.mkdir(parents=True)
            (latest/'limits.local.json').write_text('{"providers":[{"provider":"antigravity"}]}')
            runtime = root / 'new'
            installer.import_existing_collector(home=root,runtime_dir=runtime)
            limits = json.loads((runtime/'collector/limits.json').read_text())
            self.assertEqual(limits['providers'][0]['provider'],'antigravity')
            (runtime/'collector/device.json').write_text('{"source_id":"edited"}')
            installer.import_existing_collector(home=root,runtime_dir=runtime)
            self.assertEqual(json.loads((runtime/'collector/device.json').read_text())['source_id'],'edited')
