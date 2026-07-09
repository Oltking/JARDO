#!/usr/bin/env bash
# Build the Jardo macOS app + DMG.
#
# Output: desktop/src-tauri/target/release/bundle/dmg/Jardo_<version>_<arch>.dmg
#
# Self-contained: the Python core is frozen into a sidecar (embedded SQLite +
# in-process queue, no Postgres/Redis/Docker) and bundled inside the .app. Voice
# libraries ship in the bundle; the voice MODEL (~180 MB) downloads on first use,
# keeping this DMG small (~110-130 MB). See PACKAGING.md.
set -euo pipefail

cd "$(dirname "$0")/.."

# Always refreshe the frozen core so a release DMG can never bundle stale code.
# (Set JARDO_SKIP_CORE_BUILD=1 to reuse the staged one during rapid shell-only iteration.)
if [ "${JARDO_SKIP_CORE_BUILD:-0}" = "1" ] && [ -x "desktop/src-tauri/resources/jardo-core/jardo-core" ]; then
  echo "==> JARDO_SKIP_CORE_BUILD=1 — reusing staged core (may be stale)"
else
  echo "==> Freezing the Python core (sidecar) from current source…"
  ./scripts/build-core-binary.sh
fi

cd desktop

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
