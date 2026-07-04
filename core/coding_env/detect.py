"""Detect installed coding environments (editors, terminals, shells, agents).

This is the coding-scoped inventory (spec §7.5, narrowed to coding tools per
owner scope). Pure detection — no launching, no side effects. The registries
below are also the **allow-list**: the operator will only open tools known here,
which is how "coding environments only" is enforced.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

_APPS_DIR = Path("/Applications")


@dataclass(frozen=True)
class EditorSpec:
    key: str
    name: str          # macOS .app name
    cli: str           # CLI command if installed on PATH
    goto_flag: str | None  # flag to open at file:line (e.g. "-g" for VS Code family)


# Coding editors/IDEs allow-list. VS Code family CLIs take `-g path:line`.
CODING_EDITORS: dict[str, EditorSpec] = {
    "vscode": EditorSpec("vscode", "Visual Studio Code", "code", "-g"),
    "cursor": EditorSpec("cursor", "Cursor", "cursor", "-g"),
    "windsurf": EditorSpec("windsurf", "Windsurf", "windsurf", "-g"),
    "zed": EditorSpec("zed", "Zed", "zed", None),
    "sublime": EditorSpec("sublime", "Sublime Text", "subl", None),
    "pycharm": EditorSpec("pycharm", "PyCharm", "pycharm", "--line"),
    "idea": EditorSpec("idea", "IntelliJ IDEA", "idea", "--line"),
    "nvim": EditorSpec("nvim", "", "nvim", None),   # terminal editor
    "vim": EditorSpec("vim", "", "vim", None),
}

# Terminal emulators (macOS .app names) considered "coding terminals".
CODING_TERMINALS = [
    "Terminal", "iTerm", "Warp", "Alacritty", "kitty", "WezTerm", "Ghostty", "Hyper",
]

# Shells Jardo may drive (command prompts / PowerShell / coding terminals).
CODING_SHELLS = ["zsh", "bash", "pwsh", "fish", "nu"]

# CLI coding agents Jardo supervises/answers (spec §4.3).
CODING_AGENTS = {
    "claude": "Claude Code",
    "aider": "aider",
    "cursor-agent": "Cursor Agent",
    "codex": "OpenAI Codex CLI",
}

# Coding CLIs worth knowing about for context/tasks.
CODING_CLIS = ["git", "gh", "node", "python3", "uv", "docker", "cargo", "pnpm", "npm"]


def _app_installed(app_name: str) -> bool:
    if not app_name:
        return False
    return (_APPS_DIR / f"{app_name}.app").exists() or \
        (Path("/System/Applications/Utilities") / f"{app_name}.app").exists()


@dataclass
class Inventory:
    editors: dict[str, str] = field(default_factory=dict)   # key -> "cli" | "app"
    terminals: list[str] = field(default_factory=list)
    shells: dict[str, str] = field(default_factory=dict)    # name -> path
    agents: dict[str, str] = field(default_factory=dict)    # cli -> label
    clis: dict[str, str] = field(default_factory=dict)      # name -> path

    def as_dict(self) -> dict:
        return {
            "editors": self.editors,
            "terminals": self.terminals,
            "shells": self.shells,
            "agents": self.agents,
            "clis": self.clis,
        }


def detect() -> Inventory:
    inv = Inventory()
    for key, spec in CODING_EDITORS.items():
        if spec.cli and shutil.which(spec.cli):
            inv.editors[key] = "cli"
        elif _app_installed(spec.name):
            inv.editors[key] = "app"
    inv.terminals = [t for t in CODING_TERMINALS if _app_installed(t)]
    for sh in CODING_SHELLS:
        path = shutil.which(sh)
        if path:
            inv.shells[sh] = path
    for cli, label in CODING_AGENTS.items():
        if shutil.which(cli):
            inv.agents[cli] = label
    for cli in CODING_CLIS:
        path = shutil.which(cli)
        if path:
            inv.clis[cli] = path
    return inv
