"""Terminal driver selection (Lane A): Terminal.app + iTerm2 are scriptable;
Warp / VS Code route to the hook (driver = None)."""

from core.agents.terminals import ITerm, TerminalApp, get_driver


def test_selects_scriptable_terminals():
    assert isinstance(get_driver("terminal"), TerminalApp)
    assert isinstance(get_driver("iterm"), ITerm)
    assert isinstance(get_driver("Terminal"), TerminalApp)  # case-insensitive


def test_hook_only_terminals_return_none():
    for name in ("warp", "vscode", "code", "Warp"):
        assert get_driver(name) is None, name


def test_unknown_or_empty_defaults_to_terminal_app():
    assert isinstance(get_driver("somethingelse"), TerminalApp)
    assert isinstance(get_driver(""), TerminalApp)


def test_supervised_terminal_ok_follows_setting(monkeypatch):
    # The runtime override (appsettings, written by the Settings UI) is the source
    # of truth for which terminal Jardo drives.
    from core import appsettings
    from core.agents import terminal_watch
    choice = {"supervise_terminal": "warp"}
    monkeypatch.setattr(appsettings, "get", lambda k, d=None: choice.get(k, d))
    assert terminal_watch.supervised_terminal_ok() is False  # Warp → hook-only
    choice["supervise_terminal"] = "iterm"
    assert terminal_watch.supervised_terminal_ok() is True


def test_driver_interface_is_complete():
    # Both drivers implement the full surface supervision relies on.
    for d in (TerminalApp(), ITerm()):
        for method in ("read", "send_keys", "open", "front_window", "is_frontmost"):
            assert callable(getattr(d, method))
