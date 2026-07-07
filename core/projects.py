"""Tracked projects and the "where am I?" resume summary (spec §4.5).

A developer opens Jardo and asks "where am I?". Jardo identifies the project
(the folder they pick or the most-recent one), then answers from three cheap
sources — never by re-reading the codebase:
  1. the coding agent's own memory (core.agent_memory: Claude's title +
     compaction summary + last prompt),
  2. git (what's committed = done, what's uncommitted/unpushed = in progress /
     needs attention),
  3. the owner's stated goal on the project record.
"""

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent_memory import AgentMemory, read_agent_memory
from core.schema import Project


# ---- store ----------------------------------------------------------------

class ProjectStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, owner_id, path: str, name: str | None = None,
                     goal: str | None = None) -> Project:
        path = os.path.abspath(os.path.expanduser(path)).rstrip("/")
        existing = (await self.session.execute(
            select(Project).where(Project.owner_id == owner_id, Project.path == path)
        )).scalar_one_or_none()
        if existing is not None:
            existing.last_opened_at = datetime.now(timezone.utc)
            if goal:
                existing.goal = goal
            return existing
        project = Project(owner_id=owner_id, path=path,
                          name=name or os.path.basename(path) or path, goal=goal)
        self.session.add(project)
        await self.session.flush()
        return project

    async def get_active(self, owner_id) -> Project | None:
        return (await self.session.execute(
            select(Project).where(Project.owner_id == owner_id)
            .order_by(Project.last_opened_at.desc()).limit(1)
        )).scalar_one_or_none()

    async def list(self, owner_id) -> list[Project]:
        return list((await self.session.execute(
            select(Project).where(Project.owner_id == owner_id)
            .order_by(Project.last_opened_at.desc())
        )).scalars().all())


# ---- folder discovery (so the owner picks, never types a path) ------------

def list_folders(root: str) -> list[dict]:
    """Immediate subfolders of a root, newest-first — the picker list."""
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return []
    out = []
    with os.scandir(root) as it:
        for e in it:
            if e.is_dir() and not e.name.startswith("."):
                out.append({"name": e.name, "path": e.path,
                            "is_git": os.path.isdir(os.path.join(e.path, ".git")),
                            "mtime": e.stat().st_mtime})
    out.sort(key=lambda d: d["mtime"], reverse=True)
    for d in out:
        d.pop("mtime", None)
    return out


def choose_folder(prompt: str = "Pick your project folder") -> str | None:
    """Native macOS folder chooser (no extra deps). Returns a POSIX path or None
    if the owner cancels."""
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None  # user cancelled or not macOS
    return r.stdout.strip().rstrip("/") or None


# ---- git inspection -------------------------------------------------------

def _git(path: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", path, *args],
                           capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


@dataclass
class ProjectState:
    name: str
    path: str
    exists: bool
    is_git: bool
    branch: str | None = None
    recent_commits: list[str] = field(default_factory=list)
    uncommitted: int = 0
    untracked: int = 0
    unpushed: int | None = None
    goal: str | None = None
    agent: AgentMemory | None = None


def inspect_project(path: str, goal: str | None = None) -> ProjectState:
    path = os.path.abspath(os.path.expanduser(path)).rstrip("/")
    name = os.path.basename(path) or path
    if not os.path.isdir(path):
        return ProjectState(name=name, path=path, exists=False, is_git=False, goal=goal)

    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    is_git = branch is not None
    commits = (_git(path, "log", "--oneline", "-8") or "").splitlines() if is_git else []
    uncommitted = untracked = 0
    status = _git(path, "status", "--porcelain") if is_git else None
    if status:
        for ln in status.splitlines():
            if ln.startswith("??"):
                untracked += 1
            elif ln.strip():
                uncommitted += 1
    unpushed = None
    cnt = _git(path, "rev-list", "--count", "@{u}..HEAD") if is_git else None
    if cnt and cnt.isdigit():
        unpushed = int(cnt)

    agent = read_agent_memory(path)
    return ProjectState(
        name=name, path=path, exists=True, is_git=is_git, branch=branch,
        recent_commits=commits, uncommitted=uncommitted, untracked=untracked,
        unpushed=unpushed, goal=goal or (agent.title if agent else None), agent=agent,
    )


# ---- the answer -----------------------------------------------------------

def where_am_i(state: ProjectState) -> dict:
    """Turn an inspection into a spoken answer + structured fields for the UI."""
    if not state.exists:
        return {"spoken": f"I can't find a folder at {state.path}. Pick the project "
                          "folder and I'll take a look.",
                "name": state.name, "found": False}

    done: list[str] = []
    if state.recent_commits:
        done.append("recently: " + "; ".join(
            c.split(" ", 1)[-1] for c in state.recent_commits[:3]))
    if state.agent and state.agent.summary:
        done.append(state.agent.summary)

    current_bits: list[str] = []
    if state.branch:
        current_bits.append(f"on branch {state.branch}")
    if state.uncommitted or state.untracked:
        current_bits.append(
            f"{state.uncommitted} changed"
            + (f" and {state.untracked} new" if state.untracked else "")
            + " file(s) not yet committed")
    last_focus = state.agent.last_prompt if state.agent else None

    attention: list[str] = []
    if state.uncommitted or state.untracked:
        attention.append("uncommitted work to review and commit")
    if state.unpushed:
        attention.append(f"{state.unpushed} commit(s) not pushed")
    if not state.is_git:
        attention.append("this folder isn't a git repo yet")

    # Spoken answer — concise for voice.
    parts = [f"You're in {state.name}."]
    if state.goal:
        parts.append(f"Goal: {state.goal}.")
    if last_focus:
        parts.append(f"Last thing worked on: {last_focus[:200]}.")
    if current_bits:
        parts.append("Right now you're " + ", ".join(current_bits) + ".")
    if attention:
        parts.append("Worth your attention: " + "; ".join(attention) + ".")
    if not last_focus and not current_bits and not done:
        parts.append("It's quiet here — no recent agent activity or changes I can see.")
    spoken = " ".join(parts)

    return {
        "found": True,
        "name": state.name,
        "path": state.path,
        "goal": state.goal,
        "last_focus": last_focus,
        "last_active": state.agent.last_active if state.agent else None,
        "done": done,
        "current": current_bits,
        "attention": attention,
        "branch": state.branch,
        "from_agent_memory": bool(state.agent),
        "spoken": spoken,
    }
