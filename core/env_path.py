"""Repair PATH for the bundled app.

A macOS .app launched from Finder inherits a minimal PATH (/usr/bin:/bin), NOT
the user's shell PATH. So coding-agent CLIs (claude, gemini), npm, and git that
live in ~/.local/bin, /opt/homebrew/bin, etc. are invisible — "claude cli not in
path" even though it's right there in the user's terminal.

ensure_full_path() merges in the real login-shell PATH plus the common install
locations, so tool detection and launches work the same as the user's terminal.
"""

import os
import subprocess

# Common places CLIs land, checked directly (fast, no subprocess needed).
_COMMON = [
    "~/.local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
    "~/.claude/local", "~/bin", "~/.npm-global/bin", "~/.bun/bin", "~/.deno/bin",
    "~/.volta/bin", "~/.nvm/current/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
]


def _login_shell_path() -> str:
    """The user's real PATH, as their login shell sees it. Best-effort + bounded."""
    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        out = subprocess.run(
            [shell, "-lic", "printf %s \"$PATH\""],
            capture_output=True, text=True, timeout=4,
        )
        # -i can print shell noise; take the last non-empty line.
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else ""
    except Exception:  # noqa: BLE001 — never let PATH repair break startup
        return ""


def ensure_full_path() -> None:
    parts = [p for p in os.environ.get("PATH", "").split(":") if p]
    seen = set(parts)
    candidates = _login_shell_path().split(":") + [os.path.expanduser(d) for d in _COMMON]
    for d in candidates:
        d = d.strip()
        if d and d not in seen and os.path.isdir(d):
            parts.append(d)
            seen.add(d)
    os.environ["PATH"] = ":".join(parts)
