"""Interactive permission-prompt detection + decision (pure logic) and an
end-to-end SupervisedAgent run against a fake agent script."""

import sys
import textwrap

import pytest

from core.coding_env.prompt_responder import decide_answer, detect_prompt
from core.schema import Policy
from core.sentinel.models import Verdict


# ---- detection -----------------------------------------------------------

def test_detects_y_n_prompt_with_signal():
    buf = "Jardo wants to run: npm install\nDo you want to proceed? (y/n) "
    m = detect_prompt(buf)
    assert m is not None
    assert (m.yes_token, m.no_token) == ("y", "n")
    assert "npm install" in m.proposed_action


def test_detects_yes_no_words():
    buf = "Run shell command:\n  rm -rf build/\nProceed? (yes/no): "
    m = detect_prompt(buf)
    assert m is not None
    assert (m.yes_token, m.no_token) == ("yes", "no")
    assert "rm -rf build/" in m.proposed_action


def test_detects_aider_style():
    buf = "Run shell command?\n  git push --force\n(Y)es/(N)o [Yes]: "
    m = detect_prompt(buf)
    assert m is not None
    assert m.yes_token == "y"


def test_ignores_non_prompt_output():
    assert detect_prompt("Installing packages...\nDone in 3.2s\n") is None
    assert detect_prompt("the file is y/n formatted somewhere in prose") is None


def test_terse_yn_at_line_end_without_signal_word():
    # a bare "[y/N]" at the end still counts
    assert detect_prompt("Overwrite existing file [y/N] ") is not None


# ---- decision ------------------------------------------------------------

def test_decide_answer_maps_verdict_to_token():
    m = detect_prompt("proceed? (y/n) ")
    assert decide_answer(m, Verdict.APPROVE) == "y"
    assert decide_answer(m, Verdict.DENY) == "n"
    assert decide_answer(m, Verdict.ESCALATE) == "n"  # decline = safe default


# ---- end-to-end via a fake agent ----------------------------------------

_FAKE_AGENT = textwrap.dedent("""
    import sys
    print("Fake coding agent")
    print("I want to run: %s")
    ans = input("Do you want to proceed? (y/n) ")
    print("ANSWER=" + ans.strip())
""")


async def _run_agent(session, command_to_ask: str):
    from core.coding_env.supervised_agent import SupervisedAgent
    script = _FAKE_AGENT % command_to_ask
    agent = SupervisedAgent(session)
    # run the fake agent via python reading the embedded script
    return await agent.run(
        f"{sys.executable} -c {_shquote(script)}",
        stated_goal="run my project setup with ls",
    )


def _shquote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


@pytest.mark.skipif(sys.platform == "win32", reason="pty POSIX only")
async def test_supervised_agent_declines_dangerous_prompt(session):
    result = await _run_agent(session, "rm -rf /")
    assert result["decisions"], "should have caught the prompt"
    d = result["decisions"][0]
    assert d["answered"] == "n"  # rm -rf / is critical → declined
    assert "ANSWER=n" in result["transcript_tail"]


@pytest.mark.skipif(sys.platform == "win32", reason="pty POSIX only")
async def test_supervised_agent_approves_policied_prompt(session):
    session.add(Policy(action_type="shell.run", target_pattern=r"ls.*",
                       tier="always-allow"))
    await session.flush()
    result = await _run_agent(session, "ls -la with ls")
    d = result["decisions"][0]
    assert d["answered"] == "y"
    assert "ANSWER=y" in result["transcript_tail"]


# ---- numbered menu (Claude Code style) -----------------------------------

def test_detects_claude_code_numbered_menu():
    buf = (
        "Bash command\n"
        "  git push --force origin main\n"
        "\n"
        "Do you want to proceed?\n"
        "❯ 1. Yes\n"
        "  2. Yes, and don't ask again for git commands\n"
        "  3. No, and tell Claude what to do differently (esc)\n"
    )
    m = detect_prompt(buf)
    assert m is not None
    assert m.yes_token == "1"
    assert m.no_token == "3"
    assert "git push --force" in m.proposed_action


def test_numbered_menu_without_signal_ignored():
    # a numbered list that isn't a permission prompt
    buf = "Results:\n1. yesterday\n2. nowhere\n"
    assert detect_prompt(buf) is None


def test_numbered_menu_decision():
    buf = ("Do you want to proceed?\n1. Yes\n2. No\n")
    m = detect_prompt(buf)
    from core.sentinel.models import Verdict
    assert decide_answer(m, Verdict.APPROVE) == "1"
    assert decide_answer(m, Verdict.DENY) == "2"
