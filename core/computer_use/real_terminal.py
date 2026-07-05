"""Drive the owner's REAL terminal (macOS Terminal.app) — not a sandbox PTY.

Runs commands in an actual Terminal window (the owner sees them live) and
captures exact output via `tee` to a temp file plus a done-marker, which is far
more reliable than reading the AppleScript `history`. Every command passes a
gate callback first (the autonomous decider) — no ungated execution (§0.3).

macOS-only (AppleScript). iTerm support can be added the same way later.
"""

import os
import re
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# gate(command, goal) -> (approve: bool, reason: str)
Gate = Callable[[str, str], Awaitable[tuple[bool, str]]]


@dataclass
class TerminalResult:
    approved: bool
    ran: bool
    output: str
    exit_status: int | None
    reason: str


class RealTerminal:
    def __init__(self, gate: Gate | None = None):
        self._gate = gate
        self._window_id: int | None = None

    def _osa(self, *lines: str) -> str:
        args = ["osascript"]
        for ln in lines:
            args += ["-e", ln]
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def open(self) -> int | None:
        """Open (or reuse) a dedicated Jardo Terminal window; return its id."""
        out = self._osa(
            'tell application "Terminal" to activate',
            'tell application "Terminal" to do script ""',
        )
        m = re.search(r"window id (\d+)", out)
        self._window_id = int(m.group(1)) if m else None
        return self._window_id

    async def run(self, command: str, goal: str, timeout: float = 120.0) -> TerminalResult:
        # Gate first — refuse anything unsafe/off-task (the decider acts for the owner).
        reason = "no gate"
        if self._gate is not None:
            approve, reason = await self._gate(command, goal)
            if not approve:
                return TerminalResult(False, False, "", None, reason)

        if self._window_id is None:
            self.open()

        token = uuid.uuid4().hex[:8]
        out_f = f"/tmp/jardo_out_{token}.txt"
        exit_f = f"/tmp/jardo_exit_{token}.txt"
        done_f = f"/tmp/jardo_done_{token}.txt"
        script_f = f"/tmp/jardo_cmd_{token}.sh"
        with open(script_f, "w") as f:
            # tee → the owner sees it live AND we capture it; PIPESTATUS = the
            # command's exit code (not tee's); a done-marker signals completion.
            f.write(f"{command} 2>&1 | tee {out_f}\n")
            f.write(f"echo ${{PIPESTATUS[0]}} > {exit_f}\n")
            f.write(f"echo done > {done_f}\n")

        self._osa(
            f'tell application "Terminal" to do script "bash {script_f}" '
            f"in window id {self._window_id}"
        )
        start = time.time()
        while not os.path.exists(done_f):
            if time.time() - start > timeout:
                return TerminalResult(True, True, _read(out_f), None,
                                      f"{reason} (timed out after {timeout:.0f}s)")
            time.sleep(0.3)

        output = _read(out_f)
        exit_status = _read_int(exit_f)
        for path in (out_f, exit_f, done_f, script_f):
            try:
                os.remove(path)
            except OSError:
                pass
        return TerminalResult(True, True, output, exit_status, reason)


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_int(path: str) -> int | None:
    txt = _read(path)
    try:
        return int(txt)
    except ValueError:
        return None
