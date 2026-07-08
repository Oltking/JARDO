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


CLAUDE_BOXED = """\
╭──────────────────────────────────────────────────────────────╮
│ Bash command                                                 │
│ rm -rf build && npm run build                                │
│                                                              │
│ Do you want to proceed?                                      │
│ ❯ 1. Yes                                                     │
│   2. Yes, and don't ask again for npm commands               │
│   3. No, and tell Claude what to do differently (esc)        │
╰──────────────────────────────────────────────────────────────╯
"""


def test_detects_boxed_prompt_despite_tui_borders():
    p = detect_permission_prompt(CLAUDE_BOXED)
    assert p is not None, "must see through Claude's box-drawing border"
    assert p.numbered is True
    assert p.approve_key == "1"
    assert p.deny_key == "3"
    assert "npm run build" in p.action


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


CLAUDE_TRUST = """\
╭──────────────────────────────────────────────────────────────╮
│ Do you trust the files in this folder?                       │
│                                                              │
│ /Users/dev/projects/new-app                                  │
│                                                              │
│ Claude Code may read files in this folder.                   │
│                                                              │
│ ❯ 1. Yes, proceed                                            │
│   2. No, exit                                                │
╰──────────────────────────────────────────────────────────────╯
"""


CLAUDE_TRUST_V2 = """\
 Accessing workspace:
 /Users/dev/projects/thing

 Quick safety check: Is this a project you created or one you trust?

 Claude Code'll be able to read, edit, and execute files here.

 ❯ 1. Yes, I trust this folder
   2. No, exit
"""


def test_detects_new_trust_prompt_wording():
    # Claude changed the wording — no "Do you trust…" question line anymore.
    p = detect_permission_prompt(CLAUDE_TRUST_V2)
    assert p is not None and p.kind == "trust"
    assert p.approve_key == "1"  # Yes, I trust this folder
    assert p.deny_key == "2"     # No, exit


def test_detects_folder_trust_prompt():
    # Claude's FIRST prompt in a new folder — onboarding stalls if this is missed.
    p = detect_permission_prompt(CLAUDE_TRUST)
    assert p is not None
    assert p.kind == "trust"
    assert p.approve_key == "1"  # "Yes, proceed"
    assert p.deny_key == "2"     # "No, exit"


def test_question_without_options_or_yn_does_not_fire():
    # Prose that merely contains a question must never trigger a keypress.
    prose = "● I could refactor this. Do you want me to explain the approach first?"
    assert detect_permission_prompt(prose) is None


def test_only_looks_at_the_tail():
    # An old prompt far up the scrollback, with lots of work since, must not fire.
    stale = CLAUDE_BASH + "\n" + ("● working…\n" * 60)
    assert detect_permission_prompt(stale) is None
