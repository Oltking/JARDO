"""Model-based intent understanding — the tool-use layer.

Replaces brittle keyword regexes with comprehension: the model reads what the
owner *meant* and picks an action, so "supervise it", "keep clicking yes",
"watch what Claude is doing", and even STT manglings like "super vice" all map
to the right thing without anyone enumerating phrases.

Returns a small structured intent the desktop dispatches to its existing
handlers. Pure prompt + parse here; the model call and dispatch live in the app.
"""

import json
import re

INTENTS = ("resume", "supervise", "new_project", "stop", "chat")

SYSTEM = """You are the intent router for Jardo, a voice assistant that supervises \
coding agents (Claude Code, Gemini CLI) in the owner's terminal.

Read the user's message and choose exactly ONE action. Reply with ONLY a JSON \
object and nothing else.

Actions:
- "resume": the user wants to know where they left off — the goal, what's done, \
what's left, or to catch up / pick up a project.
- "supervise": the user wants Jardo to watch the terminal and answer a coding \
agent's yes/no permission prompts for them (e.g. "supervise claude", "keep \
clicking yes", "watch what it's doing", "handle the prompts", "take over"). \
Include "agent" (claude, gemini, codex, or cursor) if named, else "claude".
- "new_project": the user wants to START or BUILD a NEW project/app/website/tool \
with an agent. Put a short description in "goal" and the agent in "agent" \
(default "claude").
- "stop": the user wants to stop/halt supervising or listening.
- "chat": anything else — a question, conversation, or request that is not one of \
the above.

Schema: {"intent": "resume"|"supervise"|"new_project"|"stop"|"chat", "agent": \
string (optional), "goal": string (optional)}

Examples:
"where was I?" -> {"intent":"resume"}
"catch me up on what I'm working on" -> {"intent":"resume"}
"keep an eye on claude for me" -> {"intent":"supervise","agent":"claude"}
"just keep saying yes to the prompts" -> {"intent":"supervise","agent":"claude"}
"build me a landing page with gemini" -> {"intent":"new_project","agent":"gemini","goal":"a landing page"}
"let's create a new todo app" -> {"intent":"new_project","agent":"claude","goal":"a todo app"}
"stop watching" -> {"intent":"stop"}
"what's the capital of France?" -> {"intent":"chat"}"""


def build_messages(message: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": message}]


def parse_intent(raw: str) -> dict:
    """Extract the intent JSON from a model reply; default to chat on anything
    unexpected so a bad parse never triggers an action."""
    if not raw:
        return {"intent": "chat"}
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"intent": "chat"}
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {"intent": "chat"}
    intent = obj.get("intent")
    if intent not in INTENTS:
        return {"intent": "chat"}
    out: dict = {"intent": intent}
    agent = obj.get("agent")
    if isinstance(agent, str) and agent.strip():
        out["agent"] = agent.strip().lower()
    goal = obj.get("goal")
    if isinstance(goal, str) and goal.strip():
        out["goal"] = goal.strip()
    return out
