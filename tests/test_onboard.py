"""New-project onboarding (spec §4.5): scaffold a folder + brief for the agent."""

import os

from core.agents.onboard import (
    brief_for,
    derive_name,
    launch_shell,
    scaffold_project,
    slugify,
)


def test_derive_name_strips_filler():
    assert derive_name("build a landing page for my bakery") == "landing-page-bakery"
    assert derive_name("create a new todo app") == "todo"
    assert derive_name("!!!") == "project"


def test_slugify_is_filesystem_safe():
    assert slugify("My Cool App!") == "my-cool-app"
    assert slugify("   ") == "project"


def test_brief_targets_the_right_agent_file():
    fn, body = brief_for("claude", "acme", "build the API")
    assert fn == "CLAUDE.md" and "build the API" in body
    fn2, _ = brief_for("gemini", "acme", "x")
    assert fn2 == "GEMINI.md"


def test_scaffold_creates_folder_git_and_brief(tmp_path):
    proj = scaffold_project(str(tmp_path), "Bakery Site", "build a bakery site", "claude")
    assert os.path.isdir(proj.path)
    assert proj.name == "bakery-site"
    assert os.path.isdir(os.path.join(proj.path, ".git"))
    brief = os.path.join(proj.path, "CLAUDE.md")
    assert os.path.isfile(brief)
    assert "build a bakery site" in open(brief).read()


def test_scaffold_dedupes_existing_names(tmp_path):
    a = scaffold_project(str(tmp_path), "app", "goal one", "claude")
    b = scaffold_project(str(tmp_path), "app", "goal two", "claude")
    assert a.path != b.path
    assert b.path.endswith("app-2")


def test_launch_shell_cds_and_seeds_the_agent(tmp_path):
    line = launch_shell("claude", str(tmp_path), "claude")
    assert line.startswith(f"cd {__import__('shlex').quote(str(tmp_path))} && claude ")
    assert "CLAUDE.md" in line  # seeded to read its brief
