"""Launch a command in a VISIBLE terminal window and capture its output.

The owner watches the agent work in a real terminal (not headless). Output is
captured via tee + a done-marker file (reliable across shells).

Cross-platform: macOS drives Terminal.app (AppleScript, via RealTerminal);
Windows opens a console window; other platforms fall back to headless capture.
Windows is stubbed to the same tee+marker shape so it slots in later.
"""

import os
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass


@dataclass
class LaunchResult:
    output: str
    exit_status: int | None
    visible: bool


async def launch_visible(command: str, cwd: str, timeout: float = 900.0) -> LaunchResult:
    system = platform.system()
    if system == "Darwin":
        return await _macos(command, cwd, timeout)
    if system == "Windows":  # pragma: no cover (built here, exercised on Windows)
        return _windows(command, cwd, timeout)
    return _headless(command, cwd, timeout)


async def _macos(command: str, cwd: str, timeout: float) -> LaunchResult:
    # Reuse the real-terminal driver: runs "cd <cwd> && <command>" in a visible
    # Terminal.app window and captures the output.
    from core.computer_use.real_terminal import RealTerminal
    import shlex
    full = f"cd {shlex.quote(cwd)} && {command}"
    result = await RealTerminal(gate=None).run(full, "agent run", timeout=timeout)
    return LaunchResult(result.output, result.exit_status, visible=True)


def _windows(command: str, cwd: str, timeout: float) -> LaunchResult:  # pragma: no cover
    token = uuid.uuid4().hex[:8]
    out_f = os.path.join(os.environ.get("TEMP", "."), f"jardo_out_{token}.txt")
    done_f = os.path.join(os.environ.get("TEMP", "."), f"jardo_done_{token}.txt")
    # Open a new console window; tee-equivalent via PowerShell Tee-Object.
    ps = (f"cd '{cwd}'; {command} 2>&1 | Tee-Object -FilePath '{out_f}'; "
          f"'done' | Out-File '{done_f}'")
    subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", ps])
    start = time.time()
    while not os.path.exists(done_f) and time.time() - start < timeout:
        time.sleep(0.5)
    output = ""
    try:
        with open(out_f, encoding="utf-8", errors="replace") as f:
            output = f.read()
    except OSError:
        pass
    return LaunchResult(output[-4000:], None, visible=True)


def _headless(command: str, cwd: str, timeout: float) -> LaunchResult:
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return LaunchResult("(timed out)", None, visible=False)
    return LaunchResult(((proc.stdout or "") + (proc.stderr or ""))[-4000:],
                        proc.returncode, visible=False)
