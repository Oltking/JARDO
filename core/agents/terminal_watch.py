"""Watch the terminal the owner is ALREADY working in and answer the coding
agent's permission prompts for them (spec §4.3 acting-for-owner, §8).

The owner says "supervise Claude in my terminal". Jardo then, without disturbing
what's there:
  1. reads the front terminal's visible text (AppleScript `contents` — a passive
     read, it types nothing),
  2. detects a pending permission prompt (Claude Code's "Do you want to
     proceed?  1. Yes / 2. … / 3. No", or a plain (y/n)),
  3. pulls out the action being asked about (e.g. the Bash command),
  4. lets the autonomous decider judge it (safety + alignment with the goal),
  5. presses the answer key in that terminal — Yes when safe and on-task, No
     otherwise.

Detection and decision are pure functions (unit-tested). Only the read and the
key-press touch the OS, and both are macOS Terminal.app for now (iTerm/Warp slot
in the same way). Everything degrades gracefully: if Jardo can't read or can't
press, it reports what it would have done so the owner can press it themselves.
"""

import re
import subprocess
from dataclasses import dataclass


@dataclass
class PermissionPrompt:
    action: str          # what the agent wants to do (the command / edit target)
    question: str        # the question line ("Do you want to proceed?")
    approve_key: str     # key that means "yes" (e.g. "1" or "y")
    deny_key: str        # key that means "no"  (e.g. "3" or "n")
    numbered: bool       # numbered menu (key alone confirms) vs (y/n) (needs return)
    kind: str = "command"  # "command" | "trust" (folder-trust prompt on first launch)


_BORDER_CHARS = "│┃╎┆┇┊┋╏|┌┐└┘├┤┬┴┼─━╭╮╰╯╱╲╳ \t"


def _strip_borders(line: str) -> str:
    """Remove TUI box borders and the ❯ selection cursor from both ends of a
    line, so "│ ❯ 1. Yes │" becomes "1. Yes" (the cursor is re-added as an
    optional prefix the option regex already tolerates)."""
    line = line.strip(_BORDER_CHARS)
    line = re.sub(r"^[❯>*•]\s*", "", line)  # drop a leading selection cursor
    return line


# Questions a coding agent asks before doing something. Kept broad but anchored
# on the "do you want / trust / proceed / allow / apply" shapes Claude Code and
# Gemini use. "do you trust this folder?" is the FIRST thing Claude asks when it
# opens a new directory — Jardo must catch it or onboarding stalls immediately.
_QUESTION = re.compile(
    r"(do you want (?:to )?[^\n?]*\?|do you trust[^\n?]*\?|proceed\?|"
    r"allow this[^\n?]*\?|apply (?:this )?(?:edit|change)[^\n?]*\?)",
    re.IGNORECASE,
)
_TRUST = re.compile(r"do you trust|trust the files|trust this folder", re.IGNORECASE)
# A numbered option line: "❯ 1. Yes", "  2. Yes, and don't ask again", "3. No…".
_OPTION = re.compile(r"^\s*[❯>*]?\s*(\d+)[.)]\s+(.*\S)\s*$", re.MULTILINE)
_YN = re.compile(r"\(\s*y\s*/\s*n\s*\)\s*[:?]?\s*$", re.IGNORECASE)


def detect_permission_prompt(text: str) -> PermissionPrompt | None:
    """Find a pending permission prompt at (or near) the end of terminal text.

    Returns None when the agent is just working and hasn't asked anything — the
    common case, so this must not fire on ordinary output.
    """
    if not text:
        return None
    # Only the last handful of lines — a real prompt sits at the bottom, waiting
    # for a keypress. Looking further up invites false positives on old output.
    # Claude draws its dialog inside a box ("│ ❯ 1. Yes │"), so strip the border
    # decorations first or the option lines won't match.
    tail = "\n".join(_strip_borders(ln) for ln in text.splitlines()[-18:])

    q = _QUESTION.search(tail)
    if q:
        options = _OPTION.findall(tail[q.start():])
        if options:
            approve = _match_option(options, ("yes",), prefer_narrowest=True)
            deny = _match_option(options, ("no", "cancel", "reject"),
                                 prefer_narrowest=False)
            if approve is None or deny is None:
                return None
            action = _preceding_action(tail, q.start())
            kind = "trust" if _TRUST.search(q.group(0)) else "command"
            return PermissionPrompt(action, q.group(0).strip(), approve_key=approve,
                                    deny_key=deny, numbered=True, kind=kind)
        # A question plus an explicit (y/n) marker is the only other real prompt.
        if _YN.search(tail):
            action = _preceding_action(tail, q.start())
            kind = "trust" if _TRUST.search(q.group(0)) else "command"
            return PermissionPrompt(action, q.group(0).strip(), approve_key="y",
                                    deny_key="n", numbered=False, kind=kind)
        # A question with neither numbered options nor (y/n) is just prose —
        # never press a key on that.
        return None

    # A bare (y/n) at the very end also counts even without a "do you want" line.
    if _YN.search(tail):
        action = _preceding_action(tail, tail.rfind("("))
        return PermissionPrompt(action, tail.strip().splitlines()[-1],
                                approve_key="y", deny_key="n", numbered=False)
    return None


def _match_option(options: list[tuple[str, str]], words: tuple[str, ...],
                  prefer_narrowest: bool) -> str | None:
    """Pick the option number whose label matches one of `words`. For 'yes' we
    want the narrowest (plain "Yes", not "Yes, and don't ask again"); for 'no'
    the plain refusal."""
    hits = [(num, label) for num, label in options
            if any(w in label.lower() for w in words)]
    if not hits:
        return None
    if prefer_narrowest:
        # shortest label = least-broad grant ("Yes" over "Yes, and don't ask…")
        hits.sort(key=lambda x: len(x[1]))
    return hits[0][0]


def _preceding_action(text: str, before: int) -> str:
    """The last non-empty, non-decorative line before the question — usually the
    command or file the agent is asking to touch."""
    head = text[:before] if before > 0 else text
    for line in reversed(head.splitlines()):
        s = line.strip(" │╭╮╰╯─—•>❯*")
        s = s.strip()
        if s and not _QUESTION.search(s) and len(s) > 1:
            return s[:400]
    return ""


# ---- OS surface (macOS Terminal.app) -------------------------------------

def _osa(*lines: str) -> str:
    args = ["osascript"]
    for ln in lines:
        args += ["-e", ln]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout


def _target(window_id: int | None) -> str:
    return (f"selected tab of window id {window_id}" if window_id is not None
            else "selected tab of front window")


def front_window_id() -> int | None:
    """The id of Terminal's frontmost window, or None if there isn't one."""
    try:
        out = _osa('tell application "Terminal" to id of front window').strip()
    except RuntimeError:
        return None
    return int(out) if out.lstrip("-").isdigit() else None


def is_frontmost(window_id: int | None) -> bool:
    return window_id is not None and front_window_id() == window_id


def open_interactive(shell_command: str) -> int | None:
    """Open a new visible Terminal window running `shell_command`, and return its
    window id so supervision can pin to exactly this terminal. Returns immediately
    (unlike RealTerminal.run). The command goes through a temp script so there's
    no fragile inline AppleScript/shell escaping."""
    import os
    import tempfile
    import uuid

    path = os.path.join(tempfile.gettempdir(), f"jardo_launch_{uuid.uuid4().hex[:8]}.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n" + shell_command + "\n")
    os.chmod(path, 0o755)
    _osa('tell application "Terminal" to activate',
         f'tell application "Terminal" to do script "bash {path}"')
    return front_window_id()  # the new window is now frontmost


def read_terminal(window_id: int | None = None) -> str:
    """Passive read of a Terminal tab's text (types nothing, runs nothing). Pins
    to `window_id` when given, so supervision reads exactly the terminal it's
    watching even if the owner brings another window forward."""
    return _osa(f'tell application "Terminal" to get contents of {_target(window_id)}')


def read_front_terminal() -> str:
    return read_terminal(None)


class AccessibilityDenied(RuntimeError):
    """System Events keystroke was blocked — the owner must grant Accessibility."""


def press_answer(prompt: PermissionPrompt, approve: bool,
                 window_id: int | None = None) -> None:
    """Answer the yes/no prompt in the supervised terminal.

    Preferred path: deliver the keypress through Terminal's OWN Apple Events into
    the PINNED window — the same Automation permission the read uses. This types
    the key straight into that agent's stdin, needs no Accessibility rights, and
    doesn't steal focus (we target the window by id, not "the front app"). Falls
    back to a System Events keystroke only if that fails.
    """
    key = prompt.approve_key if approve else prompt.deny_key
    try:
        _osa(f'tell application "Terminal" to do script "{key}" in {_target(window_id)}')
        return
    except RuntimeError:
        pass  # fall through to the keystroke path

    lines = ['tell application "Terminal" to activate',
             f'tell application "System Events" to keystroke "{key}"']
    if not prompt.numbered:
        lines.append('tell application "System Events" to key code 36')  # Return
    try:
        _osa(*lines)
    except RuntimeError as exc:
        if "1002" in str(exc) or "not allowed to send keystrokes" in str(exc):
            raise AccessibilityDenied(
                "Grant Jardo Accessibility permission (System Settings → Privacy "
                "& Security → Accessibility) so it can press the answer.") from exc
        raise


def type_text(text: str, window_id: int | None = None) -> None:
    """Type a full instruction line into the agent's input and submit it (used to
    guide the agent after a decline so it adapts and keeps working, instead of
    stalling). Delivered through Terminal's Apple Events, so it lands in the
    session's stdin — the agent receives it as if the owner typed it.

    Backticks are stripped so nothing can be shell-interpreted, and quotes/
    backslashes are escaped for AppleScript."""
    clean = text.replace("`", "'").strip()
    esc = clean.replace("\\", "\\\\").replace('"', '\\"')
    _osa(f'tell application "Terminal" to do script "{esc}" in {_target(window_id)}')
