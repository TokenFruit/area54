"""Deterministic checks over the CPO's slash commands.

A command that delegates to a nonexistent agent fails silently: it runs, the
delegation resolves to nothing, and the CPO gets a plausible answer produced by
no one. These tests make that a build failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.agents import load_agents
from tools.commands import (
    Command,
    check_allowed_tools_are_known,
    check_delegation_convention,
    check_has_description,
    check_no_orphan_agents,
    check_references_resolve,
    load_commands,
    parse_command,
)

EXPECTED_COMMANDS = {"groom", "design", "build", "review", "ship", "status", "deliver"}


@pytest.fixture(scope="module")
def commands() -> list[Command]:
    return load_commands()


@pytest.fixture(scope="module")
def agent_names() -> set[str]:
    return {a.name for a in load_agents()}


def write_command(tmp_path: Path, name: str, body: str, description: str = "d") -> Command:
    path = tmp_path / f"{name}.md"
    path.write_text(f"---\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8")
    return parse_command(path)


def test_every_command_is_present(commands: list[Command]) -> None:
    assert {c.name for c in commands} == EXPECTED_COMMANDS


def test_every_command_has_a_description(commands: list[Command]) -> None:
    for command in commands:
        assert check_has_description(command) == []


def test_every_command_names_only_real_tools(commands: list[Command]) -> None:
    for command in commands:
        assert check_allowed_tools_are_known(command) == []


# --- delegation resolves --------------------------------------------------


def test_every_delegation_resolves(commands: list[Command], agent_names: set[str]) -> None:
    for command in commands:
        assert check_references_resolve(command, agent_names) == []


def test_a_typo_in_an_agent_name_is_caught(tmp_path: Path, agent_names: set[str]) -> None:
    """The failure this whole check exists to prevent."""
    command = write_command(tmp_path, "broken", "Delegate to the **architet** subagent.")
    failures = check_references_resolve(command, agent_names)
    assert len(failures) == 1
    assert "is not an agent" in failures[0]


def test_naming_an_agent_off_convention_is_caught(tmp_path: Path, agent_names: set[str]) -> None:
    """Without this, the reference check is trivially bypassed."""
    command = write_command(tmp_path, "sloppy", "Run **lead** and see what it says.")
    failures = check_delegation_convention(command, agent_names)
    assert any("outside the delegation convention" in f for f in failures)


def test_mentioning_subagents_without_delegating_is_caught(
    tmp_path: Path, agent_names: set[str]
) -> None:
    command = write_command(tmp_path, "vague", "Run the review subagent somehow.")
    failures = check_delegation_convention(command, agent_names)
    assert any("cannot see it" in f for f in failures)


# --- no orphans -----------------------------------------------------------


def test_no_agent_is_orphaned(commands: list[Command], agent_names: set[str]) -> None:
    """Every agent must be reachable from some command, or it is dead code."""
    assert check_no_orphan_agents(commands, agent_names) == []


def test_an_orphaned_agent_is_caught(tmp_path: Path) -> None:
    command = write_command(tmp_path, "only", "Delegate to the **lead** subagent.")
    failures = check_no_orphan_agents([command], {"lead", "forgotten"})
    assert len(failures) == 1
    assert "forgotten" in failures[0]


def test_a_command_without_a_description_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "nodesc.md"
    path.write_text("---\nargument-hint: x\n---\n\nbody\n", encoding="utf-8")
    assert check_has_description(parse_command(path)) == [
        "nodesc.md: missing 'description' frontmatter."
    ]
