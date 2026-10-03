"""The same collector CLI entrypoint for source installs and the frozen Mac App."""
import sys


def cli_command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--collector-cli', *arguments]
    return [sys.executable, '-m', 'ai_usage_widget.cli', *arguments]
