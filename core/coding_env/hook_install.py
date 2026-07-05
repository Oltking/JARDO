"""Install/uninstall the Jardo PreToolUse hook into a user's Claude Code
settings — user-agnostic (no hardcoded paths), idempotent, reversible.

For distribution: instead of shipping a settings snippet with an absolute path,
this resolves the hook command at install time (the `jardo-hook` console script,
or `python -m core.coding_env.pretooluse_hook`) and merges it into the user's
`~/.claude/settings.json`, preserving any existing hooks and backing up first.

Contract for the settings shape: docs/vendor/claude-code/settings.md, hooks.md.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MATCHER = "Bash|Edit|Write|WebFetch|NotebookEdit"
# Marker so we can find/remove exactly our hook without touching the user's.
_HOOK_MARKER = "jardo-hook"
_MODULE_INVOCATION = "core.coding_env.pretooluse_hook"


def default_settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json"


def resolve_hook_command() -> str:
    """Location-independent command Claude Code will run for the hook."""
    console = shutil.which("jardo-hook")
    if console:
        return console
    # Fall back to the current interpreter running the module — always valid.
    return f"{sys.executable} -m {_MODULE_INVOCATION}"


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    return {}


def _is_jardo_hook(entry: dict) -> bool:
    for h in entry.get("hooks", []):
        if _HOOK_MARKER in str(h.get("command", "")) or _MODULE_INVOCATION in str(
            h.get("command", "")
        ):
            return True
    return False


def status(path: Path | None = None) -> dict:
    path = path or default_settings_path()
    settings = _load(path)
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    installed = any(_is_jardo_hook(e) for e in pre)
    return {"installed": installed, "settings_path": str(path),
            "hook_command": resolve_hook_command()}


def install(path: Path | None = None, matcher: str = DEFAULT_MATCHER) -> dict:
    path = path or default_settings_path()
    settings = _load(path)
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])

    # Idempotent: drop any prior Jardo entry, then add the current one.
    pre[:] = [e for e in pre if not _is_jardo_hook(e)]
    pre.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": resolve_hook_command()}],
    })

    backup = None
    if path.exists():
        backup = path.with_suffix(
            f".json.jardo-bak-{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return {"installed": True, "settings_path": str(path),
            "backup": str(backup) if backup else None,
            "matcher": matcher, "hook_command": resolve_hook_command()}


def uninstall(path: Path | None = None) -> dict:
    path = path or default_settings_path()
    settings = _load(path)
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    before = len(pre)
    pre[:] = [e for e in pre if not _is_jardo_hook(e)]
    removed = before - len(pre)
    if removed:
        path.write_text(json.dumps(settings, indent=2) + "\n")
    return {"removed": removed, "settings_path": str(path)}
