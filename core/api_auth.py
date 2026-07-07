"""Local API authentication token.

The core binds to loopback only, but any local process could otherwise call
sensitive endpoints (/build/run launches an agent, /supervise, /voice/…). A
shared bearer token — generated once, stored in a 0600 file readable only by the
owner — gates every state-changing request. Legit clients (the desktop app, the
Claude hook, the CLI) read the same file. Cross-platform (file-based, not
Keychain, so Rust reads it too).
"""

import os
import secrets as pysecrets
from pathlib import Path

TOKEN_PATH = Path.home() / ".jardo" / "api_token"


def get_or_create_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = pysecrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    try:
        os.chmod(TOKEN_PATH, 0o600)  # owner-only (best effort on Windows)
    except OSError:
        pass
    return token


def read_token() -> str | None:
    try:
        return TOKEN_PATH.read_text().strip()
    except OSError:
        return None
