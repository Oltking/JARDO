"""The self-contained (SQLite) build must boot with no Postgres/Redis.

The rest of the suite configures Postgres at import time, so the engine is fixed
for the process. We exercise the embedded path in a subprocess with
JARDO_DATABASE_URL pointed at a temp SQLite file: create tables from the models
(no Alembic), run the app lifespan (in-process queue instead of Redis), and hit
healthz. This guards the packaging refactor from regressing.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT = '''
import asyncio, os, tempfile
os.environ["JARDO_DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/jardo.db"

async def main():
    import httpx
    from core.db import is_sqlite
    from core.app import app
    assert is_sqlite()
    async with app.router.lifespan_context(app):
        # In-process queue stands in for Arq/Redis.
        assert await app.state.arq.ping() is True
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/healthz")
            assert r.status_code == 200, r.text
            assert r.json()["db"] == "ok", r.text
    print("EMBEDDED_OK")

asyncio.run(main())
'''


def test_embedded_sqlite_boots_without_services() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "EMBEDDED_OK" in proc.stdout, f"stdout={proc.stdout}\nstderr={proc.stderr}"
