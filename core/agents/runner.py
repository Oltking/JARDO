"""Conduct a coding-agent run (the concept end-to-end).

prepare workspace → read spec → set the objective → launch the agent in the
folder with the composed task → the agent's permission prompts are auto-answered
(Claude via the Jardo hook against the objective) → capture output.

`execute=False` returns the plan (workspace + exact command) without running — so
the app can show "here's what I'll do" and the owner can glance before it runs.
Cross-platform: subprocess + pathlib, no OS-specific automation.
"""

import subprocess
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
    executed: bool = False
    output: str = ""
    exit_status: int | None = None
    note: str = ""
    warnings: list[str] = field(default_factory=list)


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
    command = adapter.build_command(prompt, resume and adapter.supports_resume)

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
        return AgentRun(True, agent_key, workspace.as_dict(), command,
                        note="planned (not run)", warnings=warnings)

    try:
        proc = subprocess.run(command, cwd=str(workspace.path), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return AgentRun(True, agent_key, workspace.as_dict(), command, executed=True,
                        note=f"agent timed out after {timeout:.0f}s", warnings=warnings)
    output = (proc.stdout or "") + (proc.stderr or "")
    return AgentRun(True, agent_key, workspace.as_dict(), command, executed=True,
                    output=output[-4000:], exit_status=proc.returncode,
                    note="agent finished", warnings=warnings)
