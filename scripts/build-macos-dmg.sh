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

# Stable signing identity so macOS keeps Automation/Accessibility grants across
# rebuilds (ad-hoc "-" changes identity every build and resets them). This matches
# signingIdentity in tauri.conf.json, so the cert must exist before we build.
SIGN_ID="Jardo Dev"
if ! security find-identity -p codesigning 2>/dev/null | grep -q "$SIGN_ID"; then
  echo "ERROR: code-signing identity '$SIGN_ID' not found in your keychain."
  echo "Create it once (free, no Apple account):"
  echo "    ./scripts/create-signing-cert.sh"
  echo "Then re-run this build. (This is what keeps mic/terminal permissions from"
  echo "resetting on every rebuild.)"
  exit 1
fi
echo "==> Signing with stable identity '$SIGN_ID' (grants persist across builds)"

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
echo "==> Deep-signing $APP with mic/apple-events entitlements (identity: $SIGN_ID)"
# --deep re-signs every nested dylib and the sidecar; --options runtime keeps the
# hardened runtime so the entitlements take effect.
codesign --force --deep --options runtime --entitlements "$ENT" --sign "$SIGN_ID" "$APP"
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
echo "Signed with the local '$SIGN_ID' cert (stable identity, permissions persist"
echo "across rebuilds) but NOT notarized. On YOUR Mac it runs normally. Downloaded"
echo "by others via a browser it gets quarantined, so they right-click -> Open the"
echo "first time; if macOS says 'damaged', clear the quarantine flag:"
echo "  xattr -dr com.apple.quarantine <path-to-Jardo_*.dmg>"
echo "See the README 'Installing the app build' section. Self-containment: PACKAGING.md."
