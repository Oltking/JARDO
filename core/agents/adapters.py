"""CLI coding-agent adapters — how Jardo launches each agent (cross-platform).

Each adapter knows the agent's CLI, whether it can resume a session, and how to
build the command line to run a task headlessly so Jardo can supervise it. Only
Claude Code is installed on this machine; Gemini/Cursor are scaffolded and light
up automatically once their CLI is on PATH.

Permissions: Claude Code's PreToolUse hook (jardo hook install) lets Jardo
auto-answer its tool prompts by safety+purpose — the portable, reliable path
(no TUI scraping). Agents without a hook are driven via the PTY prompt-responder.
"""

import shutil
from dataclasses import dataclass


@dataclass
class AgentAdapter:
    key: str
    cli: str
    label: str
    supports_resume: bool
    hook_permissions: bool   # True if the agent has a hook Jardo can answer through

    def installed(self) -> bool:
        return shutil.which(self.cli) is not None

    def build_command(self, prompt: str, resume: bool = False) -> list[str]:
        raise NotImplementedError


class ClaudeAdapter(AgentAdapter):
    def build_command(self, prompt: str, resume: bool = False) -> list[str]:
        # Headless run; --continue resumes the most recent session in this folder.
        # Permissions are answered by the Jardo PreToolUse hook (not skipped), so
        # Jardo stays in control of safety+purpose.
        argv = [self.cli, "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if resume:
            argv.append("--continue")
        return argv


class GeminiAdapter(AgentAdapter):
    def build_command(self, prompt: str, resume: bool = False) -> list[str]:
        # Gemini CLI: -p for a one-shot prompt. Resume flag added when confirmed
        # against the installed version.
        argv = [self.cli, "-p", prompt]
        return argv


ADAPTERS: dict[str, AgentAdapter] = {
    "claude": ClaudeAdapter("claude", "claude", "Claude Code",
                            supports_resume=True, hook_permissions=True),
    "gemini": GeminiAdapter("gemini", "gemini", "Gemini CLI",
                            supports_resume=False, hook_permissions=False),
}


def get_adapter(key: str) -> AgentAdapter | None:
    return ADAPTERS.get(key)


def installed_agents() -> dict[str, str]:
    """key -> label for agents present on PATH."""
    return {k: a.label for k, a in ADAPTERS.items() if a.installed()}
