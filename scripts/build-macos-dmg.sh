#!/usr/bin/env bash
# Build the Jardo macOS app + DMG.
#
# Output: desktop/src-tauri/target/release/bundle/dmg/Jardo_<version>_<arch>.dmg
#
# NOTE: this bundles the DESKTOP APP only. The app talks to the Python core at
# 127.0.0.1:8000, which today still needs to be running (jardo serve) plus
# Postgres + Redis. Making the DMG fully self-contained is the packaging work
# tracked in PACKAGING.md (bundle the core as a sidecar + solve the datastore
# dependency). Until then, this DMG is for testing the shell / signing flow.
set -euo pipefail

cd "$(dirname "$0")/../desktop"

echo "==> Installing frontend deps"
pnpm install

echo "==> Building frontend + Tauri bundle (targets: app, dmg)"
pnpm tauri build

DMG_DIR="src-tauri/target/release/bundle/dmg"
echo ""
echo "==> Done. DMG(s):"
ls -1 "$DMG_DIR"/*.dmg 2>/dev/null || echo "  (no .dmg found — check the build log above)"
echo ""
echo "It's UNSIGNED — see the README 'Installing the app build' section for the"
echo "right-click-to-Open steps users need. Full self-containment: PACKAGING.md."
