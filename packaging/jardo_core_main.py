"""Frozen-core entry point for the self-contained desktop build.

PyInstaller packages this into a single `jardo-core` binary that the Tauri app
spawns as a sidecar. It runs the FastAPI core in EMBEDDED mode (SQLite + an
in-process queue), so the shipped app needs no Postgres, no Redis, no Docker.

The core writes ~/.jardo/api_token on boot (core.api_auth); the desktop shell
reads it. main() blocks serving until the process is killed on app quit.
"""

import os
import sys


def main() -> None:
    # Embedded datastore + in-process jobs. Set before importing the app so the
    # config validator picks the SQLite path under ~/.jardo.
    os.environ.setdefault("JARDO_EMBEDDED", "1")

    # When frozen, bundled model files (piper voice, whisper) live next to the
    # binary; expose that root so the app can resolve them.
    if getattr(sys, "frozen", False):
        os.environ.setdefault("JARDO_BUNDLE_DIR", sys._MEIPASS)  # type: ignore[attr-defined]

    import uvicorn

    from core.app import app
    from core.config import settings

    uvicorn.run(app, host=settings.api_host, port=settings.api_port,
                log_level="warning")


if __name__ == "__main__":
    main()
