#!/usr/bin/env bash
# Freeze the Python core into a standalone binary for the self-contained desktop
# build, bundling the voice models so the shipped app is one true click: no
# Python, no services, no first-run downloads.
#
# Output: dist/jardo-core/  (jardo-core + _internal/ with libs + bundled models)
# then staged into desktop/src-tauri/resources/jardo-core/ for `pnpm tauri build`.
#
# Run from the repo root:  ./scripts/build-core-binary.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY=".venv/bin/python"
PYINSTALLER=".venv/bin/pyinstaller"

if [ ! -x "$PYINSTALLER" ]; then
  echo "PyInstaller not found. Run: uv sync --group dev --extra voice --extra denoise" >&2
  exit 1
fi

# NOTE: voice MODELS are NOT bundled — they're fetched on first use into
# ~/.jardo/models (see core/voice/stt.py). That keeps the download small (~150 MB)
# while still shipping the voice LIBRARIES, so the user never needs Python/pip.
# The whisper model (~180 MB) downloads once, then voice is fully offline.

# ---- freeze --------------------------------------------------------------
echo "==> freezing core with PyInstaller (this takes a few minutes)…"
rm -rf dist/jardo-core build/jardo-core

COLLECT_ALL=(faster_whisper ctranslate2 onnxruntime av sounddevice \
             piper tokenizers huggingface_hub numpy)
EXTRA_HIDDEN=(aiosqlite)
# optional espeak phonemizer data (piper), only if present
if "$PY" -c "import espeakng_loader" 2>/dev/null; then
  COLLECT_ALL+=(espeakng_loader)
fi
if "$PY" -c "import piper_phonemize" 2>/dev/null; then
  COLLECT_ALL+=(piper_phonemize)
fi

ARGS=(--name jardo-core --onedir --noconfirm --clean
      --distpath dist --workpath build/jardo-core --specpath build/jardo-core
      --collect-submodules uvicorn --collect-submodules core)
for m in "${COLLECT_ALL[@]}"; do ARGS+=(--collect-all "$m"); done
for h in "${EXTRA_HIDDEN[@]}"; do ARGS+=(--hidden-import "$h"); done
# Data files the core reads at runtime (resolved via core.paths.data_path).
# Absolute sources because --add-data resolves relative to --specpath, not CWD.
# The pricing table is required; routing.toml + scores.json are optional.
ARGS+=(--add-data "$ROOT/docs/vendor/fireworks/PRICING_TABLE.md:docs/vendor/fireworks")
[ -f "$ROOT/inference/routing.toml" ] && ARGS+=(--add-data "$ROOT/inference/routing.toml:inference")
[ -f "$ROOT/evals/scores.json" ] && ARGS+=(--add-data "$ROOT/evals/scores.json:evals")
# Trim weight we never ship. The denoise stack (scipy/sklearn/PIL via noisereduce)
# is an opt-in power feature that's off by default — excluding it saves ~60 MB.
for x in matplotlib tkinter PyQt5 PyQt6 PySide6 pytest \
         noisereduce scipy sklearn PIL pandas; do
  ARGS+=(--exclude-module "$x")
done

"$PYINSTALLER" "${ARGS[@]}" packaging/jardo_core_main.py

# ---- stage into the Tauri bundle resources -------------------------------
DEST="$ROOT/desktop/src-tauri/resources/jardo-core"
echo "==> staging into $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R dist/jardo-core/. "$DEST/"

echo ""
echo "==> core frozen + staged. Size: $(du -sh "$DEST" | cut -f1)"
echo "    Next: ./scripts/build-macos-dmg.sh  (runs pnpm tauri build → DMG)"
