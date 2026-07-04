"""Orchestrator executor for autonomous coding tasks (spec §1, §4.2).

A `coding` task runs a shell command under Jardo's full supervision:
  - the orchestrator's verify step gates the top-level command (Sentinel), and
  - SupervisedAgent gates any interactive "proceed? (y/n)" prompts the command
    emits, answering per policy.
The result (prompt decisions + output tail) is checkpointed by the orchestrator,
so a crash mid-task resumes cleanly (§4.2).

Register with: build_coding_orchestrator(). Task spec: {"command": "<shell>"}.
"""

import json

from core.orchestrator import Orchestrator
from core.schema import Task


async def coding_executor(task: Task, session) -> str:
    from core.coding_env.supervised_agent import SupervisedAgent

    command = task.spec.get("command", "")
    if not command:
        raise ValueError("coding task has no 'command' in spec")
    result = await SupervisedAgent(session, actor="orchestrator").run(command, task.goal)
    return json.dumps({
        "decisions": result["decisions"],
        "output_tail": result["transcript_tail"][-800:],
    })


def build_coding_orchestrator() -> Orchestrator:
    """An orchestrator that can run `coding` tasks (extend the map for more kinds)."""
    return Orchestrator({"coding": coding_executor})
