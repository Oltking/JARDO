"""Read a coding agent's OWN on-disk memory for a project, so Jardo can say
"where are you" without re-reading the codebase (which would burn tokens).

Claude Code keeps, per project, a folder of session transcripts at
  ~/.claude/projects/<path-with-slashes-as-dashes>/<session-uuid>.jsonl
Each line is a JSON event. We harvest only the cheap, high-signal fields:
  - aiTitle            → a short title of what the session is about
  - isCompactSummary   → Claude's own "story so far" (the compaction summary)
  - lastPrompt / last user message → what the agent was last asked to do
  - gitBranch, timestamp → where and when

We never load message bodies beyond text, and never touch the source tree.
"""

import json
from dataclasses import dataclass
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


@dataclass
class AgentMemory:
    title: str | None
    summary: str | None       # Claude's own compaction "story so far"
    last_prompt: str | None   # what the agent was last working on
    last_active: str | None   # ISO timestamp of the last event
    git_branch: str | None
    sessions: int             # how many sessions exist for this project
    source: str               # transcript file we read


def _encode(path: str) -> str:
    # Claude Code names the folder after the abs path with "/" → "-".
    return path.rstrip("/").replace("/", "-")


def _first_cwd(jsonl: Path) -> str | None:
    try:
        with jsonl.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("cwd"):
                    return obj["cwd"]
    except OSError:
        return None
    return None


def _find_dir(project_path: str) -> Path | None:
    direct = CLAUDE_PROJECTS / _encode(project_path)
    if direct.is_dir():
        return direct
    if not CLAUDE_PROJECTS.is_dir():
        return None
    # Fallback: the dash-encoding is ambiguous for exotic paths, so match on the
    # `cwd` Claude records inside each project's newest transcript.
    try:
        target = str(Path(project_path).resolve())
    except OSError:
        return None
    for d in CLAUDE_PROJECTS.iterdir():
        if not d.is_dir():
            continue
        sessions = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                          reverse=True)
        if sessions and (cwd := _first_cwd(sessions[0])):
            try:
                if str(Path(cwd).resolve()) == target:
                    return d
            except OSError:
                continue
    return None


def _text(message: object) -> str | None:
    """Pull plain text out of a Claude message ({content: str | [blocks]})."""
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        joined = " ".join(p for p in parts if p).strip()
        return joined or None
    return None


def read_agent_memory(project_path: str) -> AgentMemory | None:
    d = _find_dir(project_path)
    if d is None:
        return None
    sessions = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        return None
    latest = sessions[0]

    title = summary = last_prompt = last_active = branch = last_user = None
    try:
        with latest.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("aiTitle"):
                    title = obj["aiTitle"]
                if obj.get("gitBranch"):
                    branch = obj["gitBranch"]
                if obj.get("timestamp"):
                    last_active = obj["timestamp"]
                lp = obj.get("lastPrompt")
                if isinstance(lp, str) and lp.strip():
                    last_prompt = lp.strip()
                if obj.get("isCompactSummary"):
                    if s := _text(obj.get("message")):
                        summary = s
                elif obj.get("type") == "user":
                    txt = _text(obj.get("message"))
                    # Skip tool-result envelopes and system-injected blocks.
                    if txt and not txt.startswith("<") and "tool_use_id" not in txt[:60]:
                        last_user = txt
    except OSError:
        return None

    return AgentMemory(
        title=title,
        summary=(summary[:1500] if summary else None),
        last_prompt=(last_prompt or last_user),
        last_active=last_active,
        git_branch=branch,
        sessions=len(sessions),
        source=str(latest),
    )
