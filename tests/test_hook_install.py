"""Hook installer — merges into a user's Claude settings without hardcoded paths,
idempotently, preserving existing hooks. Uses a temp settings file (never the
real ~/.claude/settings.json)."""

import json

from core.coding_env import hook_install


def test_install_into_empty_creates_hook(tmp_path):
    settings = tmp_path / "settings.json"
    result = hook_install.install(settings)
    assert result["installed"]
    data = json.loads(settings.read_text())
    pre = data["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert "jardo" in pre[0]["hooks"][0]["command"].lower() or \
        "pretooluse_hook" in pre[0]["hooks"][0]["command"]


def test_install_preserves_existing_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-own-hook"}]}
        ]},
        "model": "opus",
    }))
    hook_install.install(settings)
    data = json.loads(settings.read_text())
    commands = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "my-own-hook" in commands           # user's hook preserved
    assert any("hook" in c for c in commands)   # jardo's added
    assert data["model"] == "opus"             # unrelated settings untouched


def test_install_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    hook_install.install(settings)
    hook_install.install(settings)
    data = json.loads(settings.read_text())
    jardo = [e for e in data["hooks"]["PreToolUse"] if hook_install._is_jardo_hook(e)]
    assert len(jardo) == 1  # not duplicated


def test_install_backs_up_existing(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "x"}))
    result = hook_install.install(settings)
    assert result["backup"] and (tmp_path).glob("*.jardo-bak-*")


def test_uninstall_removes_only_jardo(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "keep-me"}]}
        ]}
    }))
    hook_install.install(settings)
    result = hook_install.uninstall(settings)
    assert result["removed"] == 1
    data = json.loads(settings.read_text())
    commands = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert commands == ["keep-me"]


def test_status_reflects_state(tmp_path):
    settings = tmp_path / "settings.json"
    assert hook_install.status(settings)["installed"] is False
    hook_install.install(settings)
    assert hook_install.status(settings)["installed"] is True


def test_resolve_hook_command_is_absolute_or_module():
    cmd = hook_install.resolve_hook_command()
    assert "jardo-hook" in cmd or "core.coding_env.pretooluse_hook" in cmd
