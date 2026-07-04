import sys

import pytest

from core.computer_use.monitor import snapshot
from core.computer_use.pty_terminal import PtyTerminal, TerminalDenied
from core.sentinel.models import ActionRequest, Verdict

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX-only")


# ---------- process monitor (§7.1) ----------------------------------------

def test_snapshot_returns_live_system_state():
    snap = snapshot(top_n=3)
    assert 0.0 <= snap.memory_percent <= 100.0
    assert len(snap.top_processes) <= 3
    # this test process should be visible in the process table somewhere
    assert snap.top_processes  # non-empty on any real machine
    d = snap.as_dict()
    assert "cpu_percent" in d and "top_processes" in d


# ---------- PTY terminal (§7.2, §7.3) -------------------------------------

async def _approve(_request: ActionRequest) -> Verdict:
    return Verdict.APPROVE


async def _deny(_request: ActionRequest) -> Verdict:
    return Verdict.DENY


async def test_pty_runs_approved_command_and_reads_output():
    term = PtyTerminal(_approve)
    try:
        result = await term.run("echo hello-from-jardo", "print a greeting")
        assert "hello-from-jardo" in result.output
        assert result.exit_status == 0
    finally:
        term.close()


async def test_pty_captures_nonzero_exit():
    term = PtyTerminal(_approve)
    try:
        result = await term.run("false", "run a command that fails")
        assert result.exit_status == 1
    finally:
        term.close()


async def test_pty_refuses_denied_command_without_running_it():
    term = PtyTerminal(_deny)
    try:
        with pytest.raises(TerminalDenied):
            await term.run("rm -rf /", "free space")
    finally:
        term.close()


async def test_pty_session_persists_state_across_commands():
    term = PtyTerminal(_approve)
    try:
        await term.run("cd /tmp", "change to tmp")
        result = await term.run("pwd", "confirm working directory")
        assert "/tmp" in result.output  # same shell → cwd persisted
    finally:
        term.close()
