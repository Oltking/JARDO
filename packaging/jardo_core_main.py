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

    # Ship with the hosted free-trial proxy on by default, so the app talks with no
    # key and no Ollama out of the box. Override JARDO_PROXY_URL at run/build time
    # to point at your own deployment; set it empty to disable hosted mode.
    os.environ.setdefault("JARDO_PROXY_URL", "https://jardo.vercel.app")

    # Gemma (hackathon "Best Use of Gemma") is served by the AMD Instinct droplet
    # via ROCm — the proxy tries AMD first and substitutes its own AMD_MODEL, so the
    # app doesn't pin a Fireworks Gemma model here. The Fireworks FALLBACK uses the
    # config default chat model (gpt-oss-120b), which is a live serverless model.
    # (The old on-demand Fireworks Gemma deployment is retired: on-demand hours are
    # spent, so it 404s and can't be depended on.)

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
