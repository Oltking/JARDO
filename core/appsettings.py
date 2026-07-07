"""Small non-secret key/value store for app preferences (projects root, etc.).

Secrets still go to the Keychain (core.secrets); this is only for plain settings
the desktop panel writes. File-based (0600) so it's dead simple and cross-platform.
"""

import json
from pathlib import Path

_PATH = Path.home() / ".jardo" / "settings.json"


def _read() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return _read().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 — small deliberate kv API
    data = _read()
    data[key] = value
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2))
