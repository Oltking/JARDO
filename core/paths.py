"""Resolve repo-relative data files in both source and frozen builds.

From source, the core runs with the repo root as CWD, so a plain relative path
works. In the frozen desktop build there's no repo: PyInstaller bundles these
data files under sys._MEIPASS, which the entry point exposes as JARDO_BUNDLE_DIR.
This resolves against the bundle first, then falls back to the relative path.
"""

import os
from pathlib import Path


def data_path(rel: str) -> Path:
    bundle = os.environ.get("JARDO_BUNDLE_DIR")
    if bundle:
        p = Path(bundle) / rel
        if p.exists():
            return p
    return Path(rel)
