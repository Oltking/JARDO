#!/usr/bin/env bash
# Jardo installer — run with:
#   curl -fsSL https://jardo.vercel.app/install.sh | bash
#
# Why this instead of clicking the .dmg: a browser stamps every download with
# macOS's com.apple.quarantine flag, which makes an unsigned/un-notarized app show
# "Jardo is damaged" or the Gatekeeper block. `curl` does NOT set that flag, so
# downloading here means the app opens normally — no right-click, no Terminal
# gymnastics. We also strip quarantine as a belt-and-suspenders step.
set -euo pipefail

VERSION="v1.0.0"
ASSET="Jardo_0.1.0_aarch64.dmg"
URL="https://github.com/Oltking/JARDO/releases/download/${VERSION}/${ASSET}"
APP_NAME="Jardo.app"

say() { printf "\033[1m==>\033[0m %s\n" "$1"; }

if [ "$(uname)" != "Darwin" ]; then
  echo "Jardo is macOS-only for now."; exit 1
fi

TMP="$(mktemp -d)"
DMG="$TMP/$ASSET"
MOUNT="$TMP/mnt"
cleanup() {
  hdiutil detach "$MOUNT" -quiet >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

say "Downloading Jardo ${VERSION} (no browser quarantine this way)…"
curl -fL --progress-bar "$URL" -o "$DMG"

say "Mounting the disk image…"
mkdir -p "$MOUNT"
hdiutil attach "$DMG" -nobrowse -quiet -mountpoint "$MOUNT"

SRC="$MOUNT/$APP_NAME"
if [ ! -d "$SRC" ]; then
  # Fall back to whatever .app is inside, in case the name changes.
  SRC="$(/usr/bin/find "$MOUNT" -maxdepth 1 -name '*.app' -print -quit)"
fi
if [ -z "${SRC:-}" ] || [ ! -d "$SRC" ]; then
  echo "Couldn't find the app inside the disk image."; exit 1
fi

DEST="/Applications/$(basename "$SRC")"
if [ -d "$DEST" ]; then
  say "Replacing the existing install at $DEST…"
  rm -rf "$DEST"
fi
say "Copying to /Applications…"
# ditto preserves the bundle + code signature exactly.
ditto "$SRC" "$DEST"

# Belt-and-suspenders: curl doesn't set quarantine, but strip any that exists.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

say "Launching Jardo…"
open "$DEST"

echo ""
say "Done. Jardo is in your Applications folder."
echo "On first use, macOS will ask for Microphone (and, when you supervise, Terminal)"
echo "access — click Allow. Enjoy."
