"""Conduct a coding-agent run (the concept end-to-end).

prepare workspace → read spec → set the objective → launch the agent in the
folder with the composed task → the agent's permission prompts are auto-answered
(Claude via the Jardo hook against the objective) → capture output.

`execute=False` returns the plan (workspace + exact command) without running — so
the app can show "here's what I'll do" and the owner can glance before it runs.
Cross-platform: subprocess + pathlib, no OS-specific automation.
"""

import os
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from core.agents.adapters import get_adapter
from core.agents.workspace import compose_task, prepare_workspace


@dataclass
class AgentRun:
    ok: bool
    agent: str
    workspace: dict
    command: list[str]
    model: str | None = None
    executed: bool = False
    visible: bool = False
    output: str = ""
    exit_status: int | None = None
    note: str = ""
    warnings: list[str] = field(default_factory=list)


def _pick_model(adapter, instruction: str) -> str | None:
    """Cost optimization (§5): choose a cheaper agent model for simpler tasks,
    using the same deterministic classifier the router uses."""
    tier_models = getattr(adapter, "MODEL_BY_TIER", {})
    if not tier_models:
        return None
    from core.router.classifier import _CODE_HINT, _CRITICAL_PATTERNS
    if _CRITICAL_PATTERNS.search(instruction):
        tier = "critical"
    elif _CODE_HINT.search(instruction) or len(instruction) > 400:
        tier = "complex"
    elif len(instruction) < 80:
        tier = "trivial"
    else:
        tier = "routine"
    return tier_models.get(tier)


async def conduct(session: AsyncSession, instruction: str, agent_key: str,
                  project_dir: str, resume: bool = False, execute: bool = False,
                  timeout: float = 900.0) -> AgentRun:
    adapter = get_adapter(agent_key)
    if adapter is None:
        return AgentRun(False, agent_key, {}, [], note=f"unknown agent '{agent_key}'")
    if not adapter.installed():
        return AgentRun(False, agent_key, {}, [],
                        note=f"{adapter.label} is not installed (its CLI '{adapter.cli}' "
                        "is not on PATH)")

    workspace = prepare_workspace(project_dir)
    prompt = compose_task(instruction, workspace)
    model = _pick_model(adapter, instruction)
    command = adapter.build_command(prompt, resume and adapter.supports_resume, model)

    warnings: list[str] = []
    # Set the objective so the agent's actions are judged against this task
    # (the hook / supervisor uses the active objective for alignment).
    from core.memory import MemoryStore
    from core.supervision import start_session
    owner = await MemoryStore(session).get_owner()
    if owner is not None:
        await start_session(session, owner.id, instruction, agent=agent_key)
        await session.commit()

    if adapter.hook_permissions:
        from core.coding_env.hook_install import status as hook_status
        if not hook_status()["installed"]:
            warnings.append(
                "The Jardo permission hook isn't installed, so Claude's prompts "
                "won't be auto-answered. Run: jardo hook install")

    if not execute:
        return AgentRun(True, agent_key, workspace.as_dict(), command, model=model,
                        note="planned (not run)", warnings=warnings)

    # Gate the agent launch itself through the Sentinel (§0.3 — no ungated
    # execution). The command is constructed, but this closes the path entirely.
    from core.autonomy.decider import autonomous_decision
    decision = await autonomous_decision(
        session, f"{adapter.cli} (build task: {instruction})", instruction)
    if not decision.approve:
        return AgentRun(False, agent_key, workspace.as_dict(), command, model=model,
                        note=f"refused: {decision.reason}", warnings=warnings)

    # Write the prompt to a file (avoids quoting the spec) and run the agent in a
    # VISIBLE terminal so the owner can watch it work.
    import tempfile
    from core.agents.terminal_launch import launch_visible

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as pf:
        pf.write(prompt)
        prompt_file = pf.name
    shell_cmd = adapter.build_shell_command(
        prompt_file, resume and adapter.supports_resume, model)
    result = await launch_visible(shell_cmd, command, str(workspace.path), timeout)
    try:
        os.remove(prompt_file)
    except OSError:
        pass
    return AgentRun(True, agent_key, workspace.as_dict(), command, model=model,
                    executed=True, visible=result.visible, output=result.output,
                    exit_status=result.exit_status, note="agent finished",
                    warnings=warnings)
