"""Conversational build intake (owner concept): before running a coding agent,
Jardo interviews the owner — asking for everything the agent will need, one
focused question at a time, and offering smart recommendations to improve the
idea. When it has enough, it compiles a project brief and hands off to the
conductor.

Model-driven and pure: `intake_turn` takes the conversation so far + the owner's
latest message and returns Jardo's reply (a question/recommendation) or READY +
a compiled brief. Quality scales with the model — rough on the tiny local model,
sharp on a strong one.
"""

import re
from dataclasses import dataclass

_READY = re.compile(r"^\s*READY\b[:\-]?\s*", re.IGNORECASE)

# The agent Jardo is speccing for is interpolated in.
INTAKE_SYSTEM = """\
You are Jardo — a warm, sharp personal assistant. The owner wants to build \
something and will hand it to the coding agent "{agent}". Your job right now is \
to spec it out WITH them, conversationally.

Rules:
- Ask ONE focused question at a time about anything you'd need to brief {agent} \
well (purpose, audience, pages/features, tech stack, data, style/branding, \
integrations, deployment). Don't dump a list.
- Offer brief, smart recommendations where they'd improve the result \
("I'd suggest X because…") — you are opinionated and helpful, not a form.
- Be concise and natural. Acknowledge what they said, then ask the next thing.
- When you have enough to write a clear, buildable brief, reply with exactly \
"READY" on the first line, then a complete project brief in markdown that {agent} \
can follow. Only say READY when you genuinely have enough."""


@dataclass
class IntakeTurn:
    reply: str          # what Jardo says back (question / recommendation / confirmation)
    ready: bool         # true when the brief is complete
    brief: str | None   # the compiled markdown brief (when ready)


def parse_build_request(text: str) -> tuple[str, str]:
    """Extract (what, agent) from an opening like 'build a website with claude'."""
    agent = "claude"
    m = re.search(r"\bwith\s+(claude|gemini|cursor|aider|codex)\b", text, re.IGNORECASE)
    if m:
        agent = m.group(1).lower()
        text = (text[:m.start()] + text[m.end():]).strip()
    what = re.sub(r"^\s*(hey\s+jardo[,]?\s*)?(let'?s\s+|please\s+|can you\s+)?"
                  r"(build|create|make|start|set up|develop)\s+(me\s+)?(a\s+|an\s+)?",
                  "", text, flags=re.IGNORECASE).strip()
    return what or text.strip(), agent


def _parse_reply(text: str) -> IntakeTurn:
    if _READY.match(text):
        brief = _READY.sub("", text, count=1).strip()
        # everything after the READY line is the brief; the reply is a handoff line
        return IntakeTurn(reply="Great — I have what I need. Here's the brief; "
                          "starting now.", ready=True, brief=brief or None)
    return IntakeTurn(reply=text.strip(), ready=False, brief=None)


async def intake_turn(agent: str, history: list[dict], user_message: str,
                      chat_fn) -> IntakeTurn:
    """chat_fn: async (messages) -> assistant text. history is prior
    {role, content} turns (excluding the system prompt)."""
    messages = [{"role": "system", "content": INTAKE_SYSTEM.format(agent=agent)}]
    messages += history
    messages.append({"role": "user", "content": user_message})
    text = await chat_fn(messages)
    return _parse_reply(text)
