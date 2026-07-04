"""Coding-environment operator — detection, allow-list enforcement, gating."""

import pytest

from core.coding_env.detect import CODING_EDITORS, detect
from core.coding_env.operator import (
    CodingOperator,
    NotACodingEnvironment,
    plan_open,
)
from core.schema import Policy
from core.sentinel.models import Verdict


# ---- detection -----------------------------------------------------------

def test_detect_returns_structured_inventory():
    inv = detect().as_dict()
    assert set(inv) == {"editors", "terminals", "shells", "agents", "clis"}
    # zsh + git exist on any dev Mac
    assert "zsh" in inv["shells"]


# ---- launch planning (pure, allow-list) ----------------------------------

def test_plan_open_rejects_non_coding_target():
    with pytest.raises(NotACodingEnvironment):
        plan_open("safari", "/tmp/x")  # not a coding editor
    with pytest.raises(NotACodingEnvironment):
        plan_open("finder", "/Users")


def test_plan_open_vscode_uses_goto_for_line(monkeypatch):
    import core.coding_env.operator as op
    monkeypatch.setattr(op.shutil, "which", lambda c: "/usr/local/bin/code")
    plan = plan_open("vscode", "/proj/main.py", line=42)
    assert plan.mode == "cli"
    assert plan.argv == ["code", "-g", "/proj/main.py:42"]


def test_plan_open_falls_back_to_open_a_without_cli(monkeypatch):
    import core.coding_env.operator as op
    monkeypatch.setattr(op.shutil, "which", lambda c: None)  # no CLI shim
    plan = plan_open("vscode", "/proj")
    assert plan.mode == "app"
    assert plan.argv == ["open", "-a", "Visual Studio Code", "/proj"]


def test_every_registered_editor_is_a_coding_tool():
    # sanity: the allow-list only contains coding editors
    assert "vscode" in CODING_EDITORS and "cursor" in CODING_EDITORS
    assert "safari" not in CODING_EDITORS and "finder" not in CODING_EDITORS


# ---- Sentinel gating -----------------------------------------------------

async def test_open_editor_escalates_without_policy(session, monkeypatch):
    import core.coding_env.operator as op
    monkeypatch.setattr(op.shutil, "which", lambda c: None)
    captured = {}
    monkeypatch.setattr(op.subprocess, "run", lambda *a, **k: captured.setdefault("ran", a))

    operator = CodingOperator(session)
    # default tier is always-ask → escalate → OperationDenied, nothing launched
    with pytest.raises(op.OperationDenied):
        await operator.open_in_editor("vscode", "/proj", "edit my project files")
    assert "ran" not in captured  # never launched an unapproved app


async def test_open_editor_launches_with_policy(session, monkeypatch):
    import core.coding_env.operator as op
    monkeypatch.setattr(op.shutil, "which", lambda c: None)
    ran = {}
    monkeypatch.setattr(op.subprocess, "run", lambda argv, **k: ran.setdefault("argv", argv))

    session.add(Policy(action_type="coding.open", target_pattern=r".*",
                       tier="always-allow"))
    await session.flush()

    operator = CodingOperator(session)
    result = await operator.open_in_editor(
        "vscode", "/proj", "open my coding project in vscode to edit")
    assert result["verdict"] == Verdict.APPROVE
    assert ran["argv"] == ["open", "-a", "Visual Studio Code", "/proj"]


async def test_run_command_review_only_does_not_execute(session):
    operator = CodingOperator(session)
    result = await operator.run_command("rm -rf /", "clean disk", review_only=True)
    assert result["executed"] is False
    assert result["verdict"] == Verdict.DENY  # critical pattern
