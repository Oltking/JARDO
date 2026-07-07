"""Project inspection + "where am I?" (spec §4.5) — cheap resume without
re-reading the codebase."""

import json
import subprocess

from core import agent_memory
from core.agent_memory import read_agent_memory
from core.projects import ProjectState, inspect_project, list_folders, where_am_i


def _write_transcript(dir_, lines):
    dir_.mkdir(parents=True, exist_ok=True)
    f = dir_ / "session.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines))
    return f


def test_reads_agent_memory_from_claude_transcript(monkeypatch, tmp_path):
    projects = tmp_path / "claude" / "projects"
    monkeypatch.setattr(agent_memory, "CLAUDE_PROJECTS", projects)
    proj_path = "/Users/dev/projects/acme"
    encoded = proj_path.replace("/", "-")
    _write_transcript(projects / encoded, [
        {"type": "user", "gitBranch": "main", "aiTitle": "Build the acme API",
         "timestamp": "2026-07-07T10:00:00Z",
         "message": {"role": "user", "content": "Add the login endpoint"}},
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "So far: scaffolded FastAPI, "
                                  "added auth models, wrote 12 tests."}]}},
        {"type": "assistant", "timestamp": "2026-07-07T10:05:00Z",
         "lastPrompt": "wire up the /login route", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "Done."}]}},
    ])
    mem = read_agent_memory(proj_path)
    assert mem is not None
    assert mem.title == "Build the acme API"
    assert "scaffolded FastAPI" in mem.summary
    assert mem.last_prompt == "wire up the /login route"
    assert mem.git_branch == "main"
    assert mem.sessions == 1


def test_find_dir_falls_back_to_cwd_match(monkeypatch, tmp_path):
    projects = tmp_path / "claude" / "projects"
    monkeypatch.setattr(agent_memory, "CLAUDE_PROJECTS", projects)
    # Folder name does NOT match the dash-encoding, but a cwd inside points home.
    real = tmp_path / "weird.dir"
    real.mkdir()
    _write_transcript(projects / "mismatched-name", [
        {"type": "user", "cwd": str(real), "message": {"role": "user", "content": "hi"}},
    ])
    mem = read_agent_memory(str(real))
    assert mem is not None and mem.sessions == 1


def test_inspect_project_reads_git_state(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_memory, "CLAUDE_PROJECTS", tmp_path / "none")
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t.test")
    run("config", "user.name", "t")
    (repo / "a.txt").write_text("hello")
    run("add", "a.txt")
    run("commit", "-qm", "first commit")
    (repo / "b.txt").write_text("wip")  # untracked, uncommitted work

    state = inspect_project(str(repo))
    assert state.exists and state.is_git
    assert any("first commit" in c for c in state.recent_commits)
    assert state.untracked == 1


def test_where_am_i_speaks_a_useful_summary():
    state = ProjectState(
        name="acme", path="/x/acme", exists=True, is_git=True, branch="main",
        recent_commits=["abc add login"], uncommitted=2, untracked=1,
        unpushed=1, goal="ship the API", agent=None)
    out = where_am_i(state)
    assert out["found"] is True
    assert "acme" in out["spoken"]
    assert "ship the API" in out["spoken"]
    assert out["attention"]  # uncommitted + unpushed flagged


def test_where_am_i_handles_missing_folder():
    out = where_am_i(ProjectState(name="gone", path="/nope", exists=False, is_git=False))
    assert out["found"] is False


def test_list_folders_lists_dirs_only(tmp_path):
    (tmp_path / "proj1").mkdir()
    (tmp_path / "proj2" / ".git").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    folders = list_folders(str(tmp_path))
    names = {f["name"] for f in folders}
    assert names == {"proj1", "proj2"}
    assert any(f["is_git"] for f in folders if f["name"] == "proj2")
