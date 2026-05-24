import json
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.widget_sync import sync_latest_to_widget


class WidgetSyncTest(unittest.TestCase):
    def test_sync_latest_to_widget_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "latest.json"
            destination = temp_path / "container" / "data" / "latest.json"
            source.write_text(json.dumps({"items": []}), encoding="utf-8")

            result = sync_latest_to_widget(str(source), str(destination))

            self.assertEqual(result, destination)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"items": []})


if __name__ == "__main__":
    unittest.main()
