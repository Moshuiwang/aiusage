from __future__ import annotations

import os
import shutil
from pathlib import Path


DEFAULT_WIDGET_BUNDLE_ID = "com.local.AIUsageWidgetApp.AIUsageWidgetExtension"


def default_widget_snapshot_path(bundle_id: str = DEFAULT_WIDGET_BUNDLE_ID) -> Path:
    home = Path.home()
    return (
        home
        / "Library"
        / "Containers"
        / bundle_id
        / "Data"
        / "Documents"
        / "ai-usage-widget"
        / "data"
        / "latest.json"
    )


def sync_latest_to_widget(source_path: str, destination_path: str | None = None) -> Path:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"latest snapshot does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"latest snapshot is not a file: {source}")

    destination = Path(destination_path) if destination_path else default_widget_snapshot_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, tmp)
    os.replace(tmp, destination)
    return destination
