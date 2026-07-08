"""Supervision comprehension — Jardo's eyes on the agent (spec §4.3).

Beyond answering permission prompts, Jardo watches the agent's terminal OUTPUT
and judges whether it's making progress, stuck in a loop, drifting off the goal,
or done — so it can flag "Claude's been stuck on the same error" instead of just
clicking Yes. Pure prompt + parse here; the model call lives in the app.
"""

import json
import re

STATES = ("progressing", "stuck", "off_task", "done", "idle", "waiting")

# States worth interrupting the owner about (vs. quiet, expected progress).
NOTABLE = frozenset({"stuck", "off_task", "done"})

SYSTEM = """You are supervising a coding agent working toward the owner's goal.
Given the goal and the agent's recent terminal output, judge its state. Reply
with ONLY a JSON object, nothing else.

States:
- progressing: making forward progress toward the goal.
- stuck: repeating the same error, looping, or blocked and not advancing.
- off_task: doing something clearly unrelated to the goal.
- done: the task appears complete (success message, tests passing, finished).
- idle: nothing meaningful happening / waiting for input.

Base your judgment ONLY on the output shown; do not invent. Keep "note" to one
short sentence addressed to the owner.

Schema: {"state": "progressing"|"stuck"|"off_task"|"done"|"idle", "note": string}"""


def build_messages(goal: str, output: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user",
         "content": f"Goal: {goal or '(none stated)'}\n\nRecent output:\n{output[-2500:]}"},
    ]


def parse_observation(raw: str) -> dict:
    if not raw:
        return {"state": "idle", "note": ""}
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"state": "idle", "note": ""}
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {"state": "idle", "note": ""}
    state = obj.get("state")
    if state not in STATES:
        state = "idle"
    note = obj.get("note", "")
    note = note.strip()[:200] if isinstance(note, str) else ""
    return {"state": state, "note": note, "notable": state in NOTABLE}
