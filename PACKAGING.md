# Packaging Jardo into a distributable app

## Where we are
The Tauri bundle config (`desktop/src-tauri/tauri.conf.json`) already targets
`app` + `dmg`, so **`scripts/build-macos-dmg.sh` produces a DMG today.** But that
DMG bundles only the **desktop shell**. For a real one-click product, two things
must be solved:

### 1. Ship + start the core (lifecycle) — DONE
The Rust app spawns the frozen core on launch and stops it on quit:
- `packaging/jardo_core_main.py` is frozen by **PyInstaller** into `jardo-core`
  (`scripts/build-core-binary.sh`), staged into `desktop/src-tauri/resources/jardo-core/`.
- `lib.rs` `spawn_core()` starts it with `JARDO_EMBEDDED=1`, `stop_core()` kills it
  on `RunEvent::Exit`. In dev (no bundled binary) it does nothing and uses the
  externally-run core.
- The `Splash` component polls `/healthz` and holds until the core is up, so there's
  a real "starting…" state and no cold-start "can't reach core" flash.

### Size: lean bundle + first-run model fetch
Voice **libraries** ship inside the app (no Python/pip on the user's machine), but
the voice **models** are not bundled — they'd be ~520 MB. Instead:
- The whisper model (~180 MB) downloads on first voice use into `~/.jardo/models`
  (`core/voice/stt.py`, `download_root`); `is_ready()` / `/voice/status`
  (`model_ready`, `model_downloading`) drive a one-time "setting up voice" banner.
- Chat, supervision, and memory work instantly with no download.
- Result: **~110-130 MB DMG** (246 MB on disk → ~99 MB gzipped core) instead of ~570 MB.
- A fully-offline variant can bundle the model via `--add-data` (see git history of
  the build script) at the cost of a larger download.

### 2. The datastore dependency — SOLVED (Option C)
The core historically needed **Postgres + pgvector** and **Redis**. A
double-click app can't require Docker, so the persistence layer is now
**dual-mode** (chosen: Option C, fully self-contained):

- Set `JARDO_EMBEDDED=1` and the core uses a **SQLite** file at `~/.jardo/jardo.db`
  (tables created from the models via `db.init_db()`, no Alembic) and runs jobs
  **in-process** (`core/inproc_queue.py`) instead of Redis/Arq — including the
  report crons.
- Semantic cache (pgvector) is Postgres-only and **degrades to exact-match** on
  SQLite; every other feature is unchanged.
- Dev/server default is still Postgres + Redis. Nothing about that path changed
  (all 251 existing tests pass; `tests/test_embedded_sqlite.py` guards the SQLite
  boot).

So the packaged app spawns one sidecar binary with `JARDO_EMBEDDED=1` — **no
Docker, no Postgres, no Redis**. The remaining packaging work is purely blocker
#1 (freeze + sidecar + lifecycle).

| Option | Self-contained? | Status |
| --- | --- | --- |
| A. Require Docker | ❌ | rejected |
| B. Bundle Postgres + Redis binaries | ✅ | rejected (heavy) |
| **C. Embed the stores (SQLite + in-process queue)** | ✅ | **done** |

## Signing
No Apple Developer cert yet → the DMG is **unsigned**. Users get a Gatekeeper
warning; the README documents the "right-click → Open" steps. When a cert is
available, add notarization to the build.

## Build (shell only, today)
```bash
./scripts/build-macos-dmg.sh
# → desktop/src-tauri/target/release/bundle/dmg/*.dmg
```

## Windows
Tauri can target Windows (`nsis`/`msi`) from a Windows machine; the same core +
datastore decision applies. The landing page shows "Windows — coming soon."
