"""Answer interactive permission prompts from CLI coding agents/tools (spec
§7.2: "this is also how it answers input/permission prompts from CLI coding
agents"; §4.3).

When a coding agent (aider, Codex, an interactive Claude Code session) or a tool
(npm, git, apt) prints a "Run this? (y/n)" style prompt and waits, Jardo — which
owns the PTY — detects the prompt, extracts the action being asked about, runs it
through the Security Sentinel, and types the answer per policy. Escalations are
answered conservatively (decline) so nothing runs without approval.

Detection + decision are pure functions (tested directly). The PTY loop lives in
SupervisedAgent, wired with the real Sentinel.
"""

import re
from dataclasses import dataclass

from core.sentinel.models import Verdict

# Answer-token hints, most specific first. Each maps to (yes_token, no_token).
_ANSWER_HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\(y\)e?s?\s*/\s*\(n\)o?", re.I), "y", "n"),            # (Y)es/(N)o
    (re.compile(r"[\(\[]\s*yes\s*/\s*no\s*[\)\]]", re.I), "yes", "no"),
    (re.compile(r"[\(\[]\s*y\s*/\s*n\s*[\)\]]", re.I), "y", "n"),
    (re.compile(r"\byes\s*/\s*no\b", re.I), "yes", "no"),
    (re.compile(r"\by\s*/\s*n\b", re.I), "y", "n"),
]

# A permission/confirmation prompt "signal" — the intent to ask for consent.
_SIGNAL = re.compile(
    r"\b(proceed|continue|overwrite|allow|confirm|are you sure|do you want|"
    r"ok to (proceed|run)|run (this |the )?(shell )?command|execute|apply this)\b",
    re.I,
)


@dataclass
class PromptMatch:
    yes_token: str
    no_token: str
    prompt_line: str
    proposed_action: str  # best-effort command/action the prompt is about


def _last_nonempty_lines(buffer: str, n: int = 6) -> list[str]:
    lines = [ln.strip() for ln in buffer.splitlines() if ln.strip()]
    return lines[-n:]


def _extract_action(lines: list[str]) -> str:
    """Best-effort: pull the command the prompt refers to from recent output."""
    for ln in reversed(lines[:-1]):  # skip the prompt line itself
        m = re.search(r"(?:run|execute|command|\$)\s*[:>]?\s*(.+)", ln, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip().strip("`'\"")
        # a bare command-looking line (has a slash, flag, or known verb)
        if re.search(r"[/\-]|^\s*(rm|git|npm|pip|curl|sudo|cd|mkdir|mv|cp)\b", ln):
            return ln
    return lines[-1] if lines else ""


# Numbered-menu options, e.g. Claude Code's "❯ 1. Yes", "3. No, and tell…".
_MENU_OPTION = re.compile(r"^[❯>*\s]*(\d+)[.)]\s*(.+)$")


def _detect_yn_inline(lines: list[str]) -> PromptMatch | None:
    tail = lines[-1]
    hint_space = " ".join(lines[-2:])
    hint = next(((y, n) for pat, y, n in _ANSWER_HINTS if pat.search(hint_space)), None)
    if hint is None:
        return None
    signal_space = " ".join(lines[-4:])
    if not _SIGNAL.search(signal_space) and not re.search(
        r"[\(\[][yY]/[nN][\)\]]\s*[:?]?\s*$", tail
    ):
        return None
    return PromptMatch(hint[0], hint[1], tail, _extract_action(lines))


def _detect_numbered_menu(lines: list[str]) -> PromptMatch | None:
    """Claude-Code-style numbered permission menu (1. Yes / 2. … / 3. No)."""
    yes_num = no_num = None
    option_lines = []
    for ln in lines:
        m = _MENU_OPTION.match(ln)
        if not m:
            continue
        num, text = m.group(1), m.group(2).strip().lower()
        option_lines.append(ln)
        if yes_num is None and text.startswith("yes"):
            yes_num = num
        if no_num is None and text.startswith("no"):
            no_num = num
    if yes_num is None or no_num is None:
        return None
    # A real menu has a consent signal nearby (e.g. "Do you want to proceed?").
    if not _SIGNAL.search(" ".join(lines)):
        return None
    context = [ln for ln in lines if ln not in option_lines]
    action = _extract_action(context) if context else ""
    return PromptMatch(yes_num, no_num, option_lines[-1], action)


def detect_prompt(buffer: str) -> PromptMatch | None:
    """Return a PromptMatch if the tail of `buffer` is an interactive permission
    prompt awaiting an answer (inline y/n or a numbered yes/no menu), else None."""
    lines = _last_nonempty_lines(buffer, n=8)
    if not lines:
        return None
    return _detect_yn_inline(lines) or _detect_numbered_menu(lines)


def decide_answer(match: PromptMatch, verdict: Verdict) -> str | None:
    """Map a Sentinel verdict to the token to type. ESCALATE/deny → decline, so
    nothing runs autonomously without approval (spec §8 presence rule)."""
    if verdict in (Verdict.APPROVE, Verdict.APPROVE_WITH_EDITS):
        return match.yes_token
    return match.no_token  # deny + escalate both decline the prompt
