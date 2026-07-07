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


_BORDER_CHARS = "│┃╎┆┇┊┋╏|┌┐└┘├┤┬┴┼─━╭╮╰╯╱╲╳ \t"


def _strip_borders(line: str) -> str:
    """Remove TUI box borders and the ❯ selection cursor from both ends of a
    line, so "│ ❯ 1. Yes │" becomes "1. Yes" (the cursor is re-added as an
    optional prefix the option regex already tolerates)."""
    line = line.strip(_BORDER_CHARS)
    line = re.sub(r"^[❯>*•]\s*", "", line)  # drop a leading selection cursor
    return line


# Questions a coding agent asks before doing something. Kept broad but anchored
# on the "do you want / proceed / allow / apply" shapes Claude Code and Gemini use.
_QUESTION = re.compile(
    r"(do you want (?:to )?[^\n?]*\?|proceed\?|allow this[^\n?]*\?|"
    r"apply (?:this )?(?:edit|change)[^\n?]*\?)",
    re.IGNORECASE,
)
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
            return PermissionPrompt(action, q.group(0).strip(), approve_key=approve,
                                    deny_key=deny, numbered=True)
        # A question plus an explicit (y/n) marker is the only other real prompt.
        if _YN.search(tail):
            action = _preceding_action(tail, q.start())
            return PermissionPrompt(action, q.group(0).strip(),
                                    approve_key="y", deny_key="n", numbered=False)
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


def open_interactive(shell_command: str) -> None:
    """Open a new visible Terminal window and start `shell_command` in it, then
    return immediately (unlike RealTerminal.run, which waits for completion). Used
    to launch an interactive coding agent the owner and Jardo both watch."""
    esc = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    _osa('tell application "Terminal" to activate',
         f'tell application "Terminal" to do script "{esc}"')


def read_front_terminal() -> str:
    """Passive read of the front Terminal tab's text. Types nothing, runs
    nothing — it cannot disturb the owner's work."""
    return _osa(
        'tell application "Terminal" to get contents of selected tab of front window'
    )


class AccessibilityDenied(RuntimeError):
    """System Events keystroke was blocked — the owner must grant Accessibility."""


def press_answer(prompt: PermissionPrompt, approve: bool) -> None:
    """Answer the yes/no prompt in the front terminal.

    Preferred path: deliver the keypress through Terminal's OWN Apple Events —
    the same Automation permission the passive read already uses — which types
    the key straight into the agent's stdin without needing Accessibility rights
    and without permanently stealing focus. Falls back to a System Events
    keystroke (which does need Accessibility) only if that fails.
    """
    key = prompt.approve_key if approve else prompt.deny_key
    try:
        # `do script … in <tab>` writes the characters into that tab's session.
        _osa(f'tell application "Terminal" to do script "{key}" '
             'in selected tab of front window')
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
