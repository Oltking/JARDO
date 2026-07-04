"""Sentinel-gated operator for coding environments (owner scope).

Two operations, both gated by the Security Sentinel (spec §6, §7.3) — no direct
execution path:
  - open_in_editor(): open a path/file in a coding editor. REFUSES any editor not
    in the coding allow-list (detect.CODING_EDITORS), enforcing "coding envs only".
  - run_command(): run a shell command in Jardo's own PTY (reuses PtyTerminal).

Launch strategy per editor: prefer the CLI (`code -g file:line`); fall back to
`open -a "<App>" <path>` when only the .app is present (e.g. VS Code without its
`code` shim on PATH). macOS-first.
"""

import shutil
import subprocess
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.coding_env.detect import CODING_EDITORS, EditorSpec
from core.sentinel.broker import Sentinel
from core.sentinel.models import ActionRequest, Verdict


class NotACodingEnvironment(ValueError):
    """Raised when asked to open something outside the coding allow-list."""


class OperationDenied(RuntimeError):
    """Raised when the Sentinel does not approve the operation."""


@dataclass
class OpenPlan:
    editor: EditorSpec
    mode: str          # "cli" | "app"
    argv: list[str]
    display: str


def plan_open(editor_key: str, path: str, line: int | None = None) -> OpenPlan:
    """Build the launch argv without running it (pure, testable). Enforces the
    coding-editor allow-list."""
    spec = CODING_EDITORS.get(editor_key)
    if spec is None:
        raise NotACodingEnvironment(
            f"'{editor_key}' is not a known coding editor; Jardo only opens coding "
            f"environments ({', '.join(sorted(CODING_EDITORS))})."
        )
    if spec.cli and shutil.which(spec.cli):
        argv = [spec.cli]
        if line and spec.goto_flag == "-g":
            argv += ["-g", f"{path}:{line}"]
        elif line and spec.goto_flag == "--line":
            argv += ["--line", str(line), path]
        else:
            argv.append(path)
        return OpenPlan(spec, "cli", argv, f"{spec.cli} {path}" + (f":{line}" if line else ""))
    if spec.name:
        # No CLI shim — open the .app bundle with the path as an argument.
        argv = ["open", "-a", spec.name, path]
        return OpenPlan(spec, "app", argv, f"open -a '{spec.name}' {path}")
    raise NotACodingEnvironment(f"{editor_key} is not installed")


class CodingOperator:
    def __init__(self, session: AsyncSession, actor: str = "jardo"):
        self._sentinel = Sentinel(session)
        self._actor = actor

    async def open_in_editor(self, editor_key: str, path: str, stated_goal: str,
                             line: int | None = None, dry_run: bool = False) -> dict:
        plan = plan_open(editor_key, path, line)
        request = ActionRequest(
            actor=self._actor, action_type="coding.open",
            target=plan.display, stated_goal=stated_goal,
            payload={"editor": editor_key, "path": path, "line": line},
        )
        review = await self._sentinel.review(request)
        if review.verdict not in (Verdict.APPROVE, Verdict.APPROVE_WITH_EDITS):
            raise OperationDenied(f"sentinel: {review.verdict} for {plan.display}")
        if not dry_run:
            subprocess.run(plan.argv, check=False)
        return {"launched": not dry_run, "argv": plan.argv, "verdict": review.verdict}

    async def run_command(self, command: str, stated_goal: str,
                          review_only: bool = False) -> dict:
        """Run a command in Jardo's PTY, Sentinel-gated. review_only returns the
        verdict without executing (useful for the CLI/UI to preview)."""
        request = ActionRequest(self._actor, "shell.run", command, stated_goal)
        review = await self._sentinel.review(request)
        if review_only or review.verdict not in (Verdict.APPROVE, Verdict.APPROVE_WITH_EDITS):
            return {"executed": False, "verdict": review.verdict,
                    "findings": [f"{f.check}: {f.message}" for f in review.findings]}
        # Deferred import: PTY needs pexpect (optional in minimal installs).
        from core.computer_use.pty_terminal import PtyTerminal, make_sentinel_review_fn
        term = PtyTerminal(make_sentinel_review_fn(self._sentinel.session))
        try:
            result = await term.run(command, stated_goal)
            return {"executed": True, "verdict": review.verdict,
                    "output": result.output, "exit_status": result.exit_status}
        finally:
            term.close()
