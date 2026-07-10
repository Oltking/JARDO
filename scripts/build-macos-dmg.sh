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

# Two-phase so we can deep-sign the .app (including the Python core sidecar)
# BEFORE the DMG is packaged. Tauri signs its own binary with the entitlements,
# but the sidecar under Resources/ is what actually opens the microphone, and it
# must carry the audio-input entitlement too or macOS feeds it silence.
echo "==> Building the .app bundle"
pnpm tauri build --bundles app

APP="src-tauri/target/release/bundle/macos/Jardo.app"
ENT="src-tauri/Entitlements.plist"
echo "==> Deep-signing $APP (ad-hoc) with mic/apple-events entitlements"
# --deep re-signs every nested dylib and the sidecar; --options runtime keeps the
# hardened runtime so the entitlements take effect; ad-hoc identity ("-").
codesign --force --deep --options runtime --entitlements "$ENT" --sign - "$APP"
echo "==> Verifying the audio-input entitlement made it into the bundle"
codesign -d --entitlements :- "$APP" 2>/dev/null | grep -q "audio-input" \
  && echo "    ok: com.apple.security.device.audio-input present" \
  || echo "    WARNING: audio-input entitlement missing — mic will stay silent"

echo "==> Packaging the DMG from the signed .app"
pnpm tauri build --bundles dmg

DMG_DIR="src-tauri/target/release/bundle/dmg"
echo ""
echo "==> Done. DMG(s):"
ls -1 "$DMG_DIR"/*.dmg 2>/dev/null || echo "  (no .dmg found — check the build log above)"
echo ""
echo "Ad-hoc signed (signingIdentity '-'), NOT notarized. Downloaded via a browser"
echo "it gets quarantined, so users right-click -> Open the first time. If macOS"
echo "still says 'damaged', clear the quarantine flag:"
echo "  xattr -dr com.apple.quarantine <path-to-Jardo_*.dmg>"
echo "See the README 'Installing the app build' section. Self-containment: PACKAGING.md."
