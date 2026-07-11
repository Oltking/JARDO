"""Terminal drivers — supervision across terminal apps (spec §4.3).

Reading the agent's buffer and typing answers is terminal-app-specific
(AppleScript). Two Mac terminals expose enough to drive:
  - Terminal.app  — pins by window id; presses via `do script` (Automation), with
    a System Events keystroke fallback (needs Accessibility).
  - iTerm2        — uses the current session; `write text` gives exact control
    over whether a newline is sent, and needs no Accessibility.

Warp and VS Code do NOT expose their buffer to AppleScript — for those (and any
terminal, and tmux/ssh) the reliable path is the Claude Code PreToolUse hook,
which supervises at the AGENT level regardless of terminal. get_driver() returns
None for them so the caller can point the owner at the hook.

The prompt PARSING (detect_permission_prompt etc.) is app-agnostic and stays in
terminal_watch; only the OS surface lives here.
"""

import subprocess

SUPPORTED = ("terminal", "iterm")            # scriptable → terminal-reading works
HOOK_ONLY = ("warp", "vscode", "code")       # not scriptable → use the hook


class AccessibilityDenied(RuntimeError):
    """System Events keystroke was blocked — the owner must grant Accessibility."""


def _osa(*lines: str) -> str:
    args = ["osascript"]
    for ln in lines:
        args += ["-e", ln]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class TerminalDriver:
    """Interface. window_id is an opaque handle the driver understands."""
    name = ""

    def installed(self) -> bool:
        return False

    def read(self, window_id=None) -> str: ...
    def front_window(self): return None
    def is_frontmost(self, window_id) -> bool: return False
    def send_keys(self, text: str, submit: bool, window_id=None) -> None: ...
    def open(self, shell_command: str): return None
    def window_exists(self, window_id) -> bool: return True


class TerminalApp(TerminalDriver):
    name = "terminal"

    def installed(self) -> bool:
        return True  # Terminal.app ships with macOS

    def _target(self, window_id) -> str:
        return (f"selected tab of window id {window_id}" if window_id is not None
                else "selected tab of front window")

    def read(self, window_id=None) -> str:
        return _osa(f'tell application "Terminal" to get contents of '
                    f'{self._target(window_id)}')

    def front_window(self):
        try:
            out = _osa('tell application "Terminal" to id of front window').strip()
        except RuntimeError:
            return None
        return int(out) if out.lstrip("-").isdigit() else None

    def is_frontmost(self, window_id) -> bool:
        return window_id is not None and self.front_window() == window_id

    def window_exists(self, window_id) -> bool:
        # Supervision ends if the owner closes the window. None → we pinned to the
        # front window; treat "any window open" as still-present.
        try:
            if window_id is None:
                return int(_osa('tell application "Terminal" to count windows').strip()) > 0
            ids = _osa('tell application "Terminal" to get id of every window')
            return str(window_id) in ids
        except RuntimeError:
            return True  # couldn't tell (transient) — don't kill supervision on a blip

    def _keystroke(self, text: str, submit: bool, window_id=None) -> None:
        # Real key events via System Events (needs Accessibility). Used for anything
        # that must be SUBMITTED, because a coding-agent TUI (Claude Code / Gemini)
        # treats do-script's tty newline as a newline INSIDE its input box rather
        # than a send — only a genuine Return keypress submits. We bring the pinned
        # window to the front first so keystrokes land in the supervised session.
        front = ['tell application "Terminal" to activate']
        if window_id is not None:
            # Best-effort focus of the exact window (ignored if it can't).
            front.append(
                f'try\ntell application "Terminal" to set frontmost of window '
                f'id {window_id} to true\nend try')
        lines = front + [
            f'tell application "System Events" to keystroke "{_esc(text)}"']
        if submit:
            lines.append('tell application "System Events" to key code 36')  # Return
        try:
            _osa(*lines)
        except RuntimeError as exc:
            if "1002" in str(exc) or "not allowed to send keystrokes" in str(exc):
                raise AccessibilityDenied(
                    "Grant Jardo Accessibility (System Settings → Privacy & "
                    "Security → Accessibility) so it can answer.") from exc
            raise

    def send_keys(self, text: str, submit: bool, window_id=None) -> None:
        # ALWAYS real keystrokes. Claude Code / Gemini are Ink TUIs that read genuine
        # key EVENTS — Terminal's `do script` pastes text into the tty, which the TUI
        # does not reliably register as a menu keypress (nor as a submit). So a
        # numbered answer is a real digit keypress (submit=False → no Return) and any
        # typed answer/guidance is keystrokes + a real Return. This needs
        # Accessibility; _keystroke raises AccessibilityDenied so the app can prompt.
        self._keystroke(text, submit=submit, window_id=window_id)

    def open(self, shell_command: str):
        import os
        import tempfile
        import time
        import uuid
        path = os.path.join(tempfile.gettempdir(),
                            f"jardo_launch_{uuid.uuid4().hex[:8]}.sh")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n" + shell_command + "\n")
        os.chmod(path, 0o755)
        # Make sure Terminal is actually running before we send Apple Events. On a
        # cold start `do script` races the app launch and fails with "Connection
        # is invalid" — `open -a` boots it via LaunchServices (no Apple Events),
        # then a short wait lets it come up so the scripted launch lands.
        was_running = _osa(
            'tell application "System Events" to (name of processes) '
            'contains "Terminal"').strip() == "true"
        if not was_running:
            subprocess.run(["open", "-a", "Terminal"], check=False)
            for _ in range(20):  # up to ~2s for Terminal to be scriptable
                time.sleep(0.1)
                try:
                    _osa('tell application "Terminal" to count windows')
                    break
                except RuntimeError:
                    continue
        _osa('tell application "Terminal" to activate',
             f'tell application "Terminal" to do script "bash {path}"')
        return self.front_window()


class ITerm(TerminalDriver):
    name = "iterm"
    _APP = "iTerm"  # AppleScript name (iTerm2's process/app is "iTerm")

    def installed(self) -> bool:
        import os
        return os.path.isdir("/Applications/iTerm.app")

    def read(self, window_id=None) -> str:
        # iTerm exposes the visible session text; pinning by id is fiddly across
        # versions, so we read the current session (best-effort).
        return _osa(f'tell application "{self._APP}" to tell current session of '
                    'current window to get text')

    def send_keys(self, text: str, submit: bool, window_id=None) -> None:
        # `write text` gives exact newline control — no Accessibility needed.
        nl = "yes" if submit else "no"
        _osa(f'tell application "{self._APP}" to tell current session of current '
             f'window to write text "{_esc(text)}" newline {nl}')

    def open(self, shell_command: str):
        _osa(f'tell application "{self._APP}" to activate',
             f'tell application "{self._APP}" to create window with default profile '
             f'command "bash -c \\"{_esc(shell_command)}\\""')
        return None


_DRIVERS = {"terminal": TerminalApp(), "iterm": ITerm()}


def get_driver(name: str) -> TerminalDriver | None:
    """The driver for a configured terminal, or None when it's hook-only (Warp/
    VS Code) or unknown — the caller then points the owner at the hook."""
    key = (name or "terminal").strip().lower()
    if key in HOOK_ONLY:
        return None
    return _DRIVERS.get(key, _DRIVERS["terminal"])
