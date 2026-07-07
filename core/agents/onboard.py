"""Start a new project and hand it to a coding agent (spec §4.5 onboarding).

The owner says "build me an X with Claude". Jardo, without them touching a
terminal:
  1. makes a project folder inside their projects root (git-initialised),
  2. writes the agent's brief to its memory file (CLAUDE.md / GEMINI.md) so the
     agent begins already knowing the goal and how to work cost-efficiently,
  3. records the project + supervision objective,
  4. opens a real terminal, cd's in, and starts the agent seeded with the goal —
     then the terminal watcher (core.agents.terminal_watch) answers its prompts.

Scaffolding is pure filesystem (unit-tested); only the launch touches the OS.
"""

import os
import re
import shlex
import subprocess
from dataclasses import dataclass

# Cost + token-budget guidance baked into every brief (owner's "don't exhaust the
# session limit" + "precision while saving cost"): work in small committed steps,
# keep context lean, stop when done.
_WORK_GUIDANCE = (
    "## How to work\n"
    "- Plan briefly, then make focused, correct changes — no broad rewrites.\n"
    "- Work in small steps and commit as you go, so progress is never lost and "
    "the session stays within its token budget.\n"
    "- Keep context lean: read what you need once; don't re-read or re-run "
    "things unnecessarily.\n"
    "- Ask before anything destructive or outside this project folder.\n"
    "- Stop once the goal is met.\n"
)


@dataclass
class NewProject:
    path: str
    name: str
    created: bool


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", text.strip().lower()).strip("-._")
    return s[:60] or "project"


def derive_name(goal: str) -> str:
    """A short folder name from a goal like 'build a landing page for my bakery'."""
    words = re.sub(r"[^a-zA-Z0-9\s]", " ", goal.lower()).split()
    skip = {"build", "create", "make", "start", "a", "an", "the", "me", "my", "new",
            "project", "please", "for", "with", "using", "of", "to", "app",
            "application", "website", "site", "some", "that", "this"}
    kept = [w for w in words if w not in skip][:4]
    return slugify(" ".join(kept) or "project")


def brief_for(agent: str, name: str, goal: str) -> tuple[str, str]:
    """(filename, contents) of the agent's project-memory brief."""
    filename = "GEMINI.md" if agent == "gemini" else "CLAUDE.md"
    body = f"# {name}\n\n## Goal\n{goal.strip()}\n\n{_WORK_GUIDANCE}"
    return filename, body


def scaffold_project(parent: str, name: str, goal: str, agent: str) -> NewProject:
    parent = os.path.abspath(os.path.expanduser(parent))
    os.makedirs(parent, exist_ok=True)
    slug = slugify(name)
    path = os.path.join(parent, slug)
    base, n = path, 2
    while os.path.exists(path):
        path, n = f"{base}-{n}", n + 1
    os.makedirs(path)
    subprocess.run(["git", "-C", path, "init", "-q"], capture_output=True)
    filename, body = brief_for(agent, os.path.basename(path), goal)
    with open(os.path.join(path, filename), "w", encoding="utf-8") as f:
        f.write(body)
    return NewProject(path=path, name=os.path.basename(path), created=True)


def launch_shell(agent_cli: str, path: str, agent: str) -> str:
    """The shell line that cd's into the project and starts the agent interactively,
    seeded to read its brief. Claude/Gemini take a positional prompt."""
    seed = ("Read the project brief in this folder (CLAUDE.md/GEMINI.md) and start "
            "building what it describes. Commit as you go; ask before anything "
            "destructive.")
    start = f"{agent_cli} {shlex.quote(seed)}" if agent in ("claude", "gemini") else agent_cli
    return f"cd {shlex.quote(path)} && {start}"
