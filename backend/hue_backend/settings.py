"""User settings (currently the wallpaper sync options), stored as JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import paths

LEGACY_WALLPAPER = Path.home() / ".config" / "omarchy" / "hue-wallpaper.json"


def path() -> Path:
    """Where the settings file lives."""
    return paths.config_dir() / "settings.json"


def load() -> Dict[str, Any]:
    """The saved settings. On first run, adopt the legacy wallpaper config and persist it.

    The legacy file is only read, never modified or deleted.
    """
    try:
        data = json.loads(path().read_text())
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    # One-time migration from the earlier standalone script's config.
    try:
        legacy = json.loads(LEGACY_WALLPAPER.read_text())
        if isinstance(legacy, dict):
            migrated = {"wallpaper": legacy}
            try:
                save(migrated)
            except OSError:
                pass  # still usable in memory; the next update retries
            return migrated
    except (OSError, ValueError):
        pass
    return {}


def save(data: Dict[str, Any]) -> None:
    """Atomically write the settings file (mode 0600)."""
    paths.write_private(path(), json.dumps(data, indent=2))
