"""Terminal permission-prompt detection (spec §4.3).

The parser must fire on a real coding-agent prompt and stay silent on ordinary
output — a false positive would make Jardo press keys into the owner's work.
"""

from core.agents.terminal_watch import detect_permission_prompt

CLAUDE_BASH = """\
● I'll run the test suite to check the change.

  Bash command
  pytest -q tests/

  Do you want to proceed?
  ❯ 1. Yes
    2. Yes, and don't ask again for pytest commands
    3. No, and tell Claude what to do differently (esc)
"""

CLAUDE_EDIT = """\
  Edit file
  src/app.py

  Do you want to make this edit?
    1. Yes
  ❯ 2. Yes, allow all edits this session
    3. No (esc)
"""

PLAIN_YN = """\
$ npm install
This will modify package-lock.json. Continue? (y/n)
"""

ORDINARY_OUTPUT = """\
● Running tests…
  12 passed in 3.1s
  All green. Next I'll refactor the router.
"""


def test_detects_bash_prompt_and_extracts_command():
    p = detect_permission_prompt(CLAUDE_BASH)
    assert p is not None
    assert p.numbered is True
    assert p.approve_key == "1"        # narrowest yes
    assert p.deny_key == "3"
    assert "pytest -q tests/" in p.action


def test_narrowest_yes_when_first_option_is_plain_yes():
    p = detect_permission_prompt(CLAUDE_EDIT)
    assert p is not None
    assert p.approve_key == "1"        # "Yes", not "Yes, allow all edits"
    assert p.deny_key == "3"
    assert "src/app.py" in p.action


def test_plain_yes_no_needs_return():
    p = detect_permission_prompt(PLAIN_YN)
    assert p is not None
    assert p.numbered is False
    assert p.approve_key == "y" and p.deny_key == "n"


def test_ignores_ordinary_output():
    assert detect_permission_prompt(ORDINARY_OUTPUT) is None
    assert detect_permission_prompt("") is None
    assert detect_permission_prompt("just some logs\nmore logs\n") is None


def test_only_looks_at_the_tail():
    # An old prompt far up the scrollback, with lots of work since, must not fire.
    stale = CLAUDE_BASH + "\n" + ("● working…\n" * 60)
    assert detect_permission_prompt(stale) is None
