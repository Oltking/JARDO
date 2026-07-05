"""Project workspace setup (cross-platform).

Creates the project folder only if it doesn't exist, otherwise reuses it, and
reads any project spec markdown found there so the agent gets the project's
context. Pure filesystem work (pathlib) — runs the same on macOS and Windows.
"""

from dataclasses import dataclass
from pathlib import Path

# Filenames that likely hold the project brief, most specific first.
_SPEC_NAMES = ["SPEC.md", "PROJECT.md", "README.md", "JARDO.md", "brief.md"]


@dataclass
class Workspace:
    path: Path
    created: bool          # True if Jardo just created the folder
    spec_file: str | None  # name of the spec md that was found
    spec: str | None       # its contents (project context for the agent)

    def as_dict(self) -> dict:
        return {"path": str(self.path), "created": self.created,
                "spec_file": self.spec_file, "has_spec": bool(self.spec)}


def prepare_workspace(path: str | Path) -> Workspace:
    """Create the folder if missing (else reuse), and load any spec markdown."""
    p = Path(path).expanduser()
    created = not p.exists()
    p.mkdir(parents=True, exist_ok=True)

    spec_file = spec = None
    for name in _SPEC_NAMES:
        candidate = p / name
        if candidate.exists() and candidate.is_file():
            spec_file = name
            spec = candidate.read_text(encoding="utf-8", errors="replace")
            break
    if spec is None:
        # fall back to the first .md in the folder, if any
        for md in sorted(p.glob("*.md")):
            spec_file, spec = md.name, md.read_text(encoding="utf-8", errors="replace")
            break

    return Workspace(path=p, created=created, spec_file=spec_file, spec=spec)


def compose_task(instruction: str, workspace: Workspace) -> str:
    """Build the prompt handed to the agent: the owner's instruction plus any
    project spec found in the folder."""
    parts = [instruction.strip()]
    if workspace.spec:
        parts.append(
            f"\n\nThe project folder already contains {workspace.spec_file} with "
            f"this brief — follow it:\n\n{workspace.spec.strip()}")
    return "".join(parts)
