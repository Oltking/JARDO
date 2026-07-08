# Packaging Jardo into a distributable app

## Where we are
The Tauri bundle config (`desktop/src-tauri/tauri.conf.json`) already targets
`app` + `dmg`, so **`scripts/build-macos-dmg.sh` produces a DMG today.** But that
DMG bundles only the **desktop shell**. For a real one-click product, two things
must be solved:

### 1. Ship + start the core (lifecycle)
The Rust app proxies to the Python core at `127.0.0.1:8000` but never *starts* it.
For a bundle we need to:
- Freeze the core into a standalone binary (**PyInstaller** → `jardo-core`),
- Add it as a Tauri **sidecar** (`externalBin`) so it's inside the .app,
- Spawn it on startup and stop it on quit (and show a "starting…" state).

### 2. The datastore dependency — the real blocker
The core needs **Postgres + pgvector** and **Redis** (via Docker today). A
double-click app can't require Docker. Three ways forward:

| Option | Self-contained? | Effort | Notes |
| --- | --- | --- | --- |
| **A. Require Docker** | ❌ (user installs Docker) | tiny | Fastest DMG; bad for non-technical users |
| **B. Bundle Postgres + Redis binaries** | ✅ | high | Ship + supervise the binaries; heavy .app, more moving parts |
| **C. Embed the stores** | ✅ | high (refactor) | SQLite + a local vector index instead of pgvector, and an in-process task queue instead of Redis/Arq. Cleanest to distribute; touches the DB/cache/worker layers |

**Recommendation:** **C** for a true consumer product (leanest install, no
services), accepting a real refactor of the persistence layer. **A** is fine for
an early tester/beta DMG while C is built.

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
