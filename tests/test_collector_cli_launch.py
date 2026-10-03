import sys
import unittest
from unittest.mock import patch
from ai_usage_widget import collector_launch
from ai_usage_widget import mac_app_collector

class CollectorLaunchTests(unittest.TestCase):
    def test_frozen_subcommands_run_bundled_cli_without_system_python(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/bundle/AIUsageCollector'):
            for command in ('mswusage-codex','mswusage-claude','mswusage-antigravity'):
                self.assertEqual(collector_launch.cli_command(command,'--json'), ['/bundle/AIUsageCollector','--collector-cli',command,'--json'])

    def test_source_install_keeps_canonical_module_entrypoint(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(collector_launch.cli_command('mswusage-codex'),[sys.executable,'-m','ai_usage_widget.cli','mswusage-codex'])

    def test_frozen_cli_dispatches_all_three_parsers_and_preserves_exit_code(self):
        for command in ('mswusage-codex','mswusage-claude','mswusage-antigravity'):
            with patch.object(sys,'argv',['helper','--collector-cli',command,'--json']), patch.object(mac_app_collector,'cli_main',return_value=7) as cli:
                self.assertEqual(mac_app_collector.main(),7)
                cli.assert_called_once_with([command,'--json'])
