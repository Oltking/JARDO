"""Supervision comprehension — Jardo's eyes on the agent (spec §4.3).

Beyond answering permission prompts, Jardo watches the agent's terminal OUTPUT
and reads EVERYTHING it can: what the agent is doing right now, the exact command
it ran, any error or blocker, concrete progress signals, and an overall state
(progressing / stuck / off-task / done / error). This is what turns Jardo from a
permission button into a real overseer — and it feeds the supervision view.

Pure prompt + parse here; the model call lives in the app.
"""

import json
import re

STATES = ("progressing", "stuck", "off_task", "done", "idle", "waiting", "error")

# States worth interrupting the owner about (vs. quiet, expected progress).
NOTABLE = frozenset({"stuck", "off_task", "done", "error"})

# The structured fields the model reports — everything it can see.
_FIELDS = ("state", "activity", "last_command", "issue", "progress", "context", "note")

SYSTEM = """You are supervising a coding agent (Claude Code / Gemini CLI) working
toward the owner's goal. Given the goal and the agent's recent terminal output,
report a precise read of EVERYTHING you can see. Reply with ONLY a JSON object,
nothing else.

Fields (use "" when a field isn't visible — never invent):
- state: progressing | stuck | off_task | done | idle | waiting | error
    progressing = advancing toward the goal; stuck = looping/blocked/repeating an
    error; off_task = doing something unrelated; done = task complete (success,
    tests passing); error = a clear failure just occurred; waiting = paused for
    input; idle = nothing meaningful happening.
- activity: a short phrase for what the agent is doing RIGHT NOW (e.g. "running
    the test suite", "editing src/app.py", "installing dependencies").
- last_command: the most recent command or tool call shown, verbatim if short
    (e.g. "pytest -q", "npm run build"), else summarized.
- issue: the actual error / failure / blocker text if any (short), else "".
- progress: a concrete progress signal if any ("12 tests passed", "build
    succeeded", "3 files changed", "server started"), else "".
- context: "low" if you see any sign the agent is running low on its context
    window (a context/token indicator near full, an auto-compact / "compacting"
    message, or the agent repeating itself or losing track for lack of context);
    otherwise "ok".
- note: ONE sentence to the owner — only meaningful when the state is notable.

Schema: {"state": ..., "activity": "", "last_command": "", "issue": "",
"progress": "", "context": "ok", "note": ""}"""


def build_messages(goal: str, output: str, brief: str = "") -> list[dict]:
    ctx = f"\n\nProject context:\n{brief[:1800]}" if brief else ""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user",
         "content": f"Goal: {goal or '(none stated)'}{ctx}"
                    f"\n\nRecent output:\n{output[-2500:]}"},
    ]


def parse_observation(raw: str) -> dict:
    empty = {f: "" for f in _FIELDS}
    empty.update({"state": "idle", "context": "ok", "notable": False})
    if not raw:
        return empty
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return empty
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return empty
    out = {}
    state = obj.get("state")
    out["state"] = state if state in STATES else "idle"
    for field in ("activity", "last_command", "issue", "progress", "note"):
        val = obj.get(field, "")
        out[field] = val.strip()[:300] if isinstance(val, str) else ""
    out["context"] = "low" if str(obj.get("context", "")).lower() == "low" else "ok"
    out["notable"] = out["state"] in NOTABLE
    return out
