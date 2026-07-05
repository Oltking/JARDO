"""Agent conductor: workspace setup, adapters, and a run against a fake agent."""

import sys

from core.agents.adapters import ClaudeAdapter, get_adapter
from core.agents.runner import conduct
from core.agents.workspace import compose_task, prepare_workspace
from core.schema import Owner


# ---- workspace -----------------------------------------------------------

def test_prepare_creates_folder_only_if_missing(tmp_path):
    target = tmp_path / "site"
    ws1 = prepare_workspace(target)
    assert ws1.created is True and target.exists()
    ws2 = prepare_workspace(target)
    assert ws2.created is False  # reused, not recreated


def test_reads_project_spec(tmp_path):
    (tmp_path / "SPEC.md").write_text("Build a bakery landing page.")
    ws = prepare_workspace(tmp_path)
    assert ws.spec_file == "SPEC.md"
    assert "bakery" in ws.spec
    task = compose_task("make it responsive", ws)
    assert "make it responsive" in task and "bakery" in task


def test_no_spec_is_fine(tmp_path):
    ws = prepare_workspace(tmp_path)
    assert ws.spec is None
    assert compose_task("just build it", ws, cost_directive=False) == "just build it"


def test_cost_directive_is_added(tmp_path):
    ws = prepare_workspace(tmp_path)
    task = compose_task("build a site", ws)
    assert "cost-efficiently" in task and "build a site" in task


# ---- adapters ------------------------------------------------------------

def test_claude_adapter_builds_headless_command():
    a = get_adapter("claude")
    cmd = a.build_command("make a website", resume=False)
    assert cmd[0] == "claude" and "-p" in cmd and "make a website" in cmd
    resumed = a.build_command("continue", resume=True)
    assert "--continue" in resumed


def test_unknown_agent_returns_none():
    assert get_adapter("nope") is None


# ---- conduct (plan + fake execution) -------------------------------------

async def _owner(session) -> Owner:
    owner = Owner(name="O", pronoun_style="sir", email="o@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


async def test_conduct_plan_only(session, tmp_path):
    await _owner(session)
    result = await conduct(session, "build a todo app", "claude", str(tmp_path),
                           execute=False)
    # claude may or may not be installed on the test host; both are valid outcomes
    if result.ok:
        assert result.executed is False
        assert result.workspace["path"] == str(tmp_path)
        assert result.command[0] == "claude"
    else:
        assert "not installed" in result.note


def test_model_is_cost_tiered_by_complexity():
    a = get_adapter("claude")
    from core.agents.runner import _pick_model
    # short/simple → cheaper model; long/complex → stronger
    assert _pick_model(a, "list files") == "haiku"
    assert _pick_model(a, "x" * 500) == "sonnet"


async def test_conduct_runs_visibly_and_captures(session, tmp_path, monkeypatch):
    await _owner(session)

    class _Fake(ClaudeAdapter):
        def installed(self):
            return True

        def build_shell_command(self, prompt_file, resume=False, model=None):
            return "echo fake-agent-built-it"

    monkeypatch.setattr("core.agents.runner.get_adapter",
                        lambda k: _Fake("claude", "claude", "Claude Code", True, True))

    # Stub the visible launcher so the test doesn't open a real terminal window.
    from core.agents.terminal_launch import LaunchResult

    async def fake_launch(command, cwd, timeout=900.0):
        import subprocess
        out = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
        return LaunchResult(out.stdout, out.returncode, visible=True)

    monkeypatch.setattr("core.agents.terminal_launch.launch_visible", fake_launch)

    result = await conduct(session, "build it", "claude", str(tmp_path), execute=True)
    assert result.ok and result.executed and result.visible
    assert "fake-agent-built-it" in result.output
