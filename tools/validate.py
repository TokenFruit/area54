"""CI entry point: fail the build if any agent or command definition is invalid.

area54 ships prompts. Most of what can go wrong here is not mechanically
decidable — but the part that is, is decided here rather than left to a reader.
"""

from __future__ import annotations

import sys

from tools.agents import AgentDefinitionError, load_agents
from tools.agents import validate as validate_agents
from tools.commands import (
    check_allowed_tools_are_known,
    check_delegation_convention,
    check_has_description,
    check_no_orphan_agents,
    check_references_resolve,
    load_commands,
)
from tools.settings import SettingsError
from tools.settings import validate as validate_settings


def validate_commands() -> list[str]:
    """Run every command check. Returns all failures."""
    agents = load_agents()
    commands = load_commands()
    names = {a.name for a in agents}
    failures: list[str] = []
    for command in commands:
        failures += check_has_description(command)
        failures += check_allowed_tools_are_known(command)
        failures += check_references_resolve(command, names)
        failures += check_delegation_convention(command, names)
    failures += check_no_orphan_agents(commands, names)
    return failures


def main() -> int:
    try:
        agents = load_agents()
        commands = load_commands()
        failures = validate_agents() + validate_commands() + validate_settings()
    except (AgentDefinitionError, SettingsError) as exc:
        print(f"::error::{exc}")
        return 1

    if failures:
        for failure in failures:
            print(f"::error::{failure}")
        print(f"\n{len(failures)} problem(s) found.")
        return 1

    print(f"{len(agents)} agents, {len(commands)} commands, and settings valid.")
    for agent in agents:
        print(f"  {agent.name:18} {agent.model:18} {', '.join(agent.tools)}")
    print()
    for command in commands:
        delegates = ", ".join(command.referenced_agents) or "—"
        print(f"  /{command.name:16} → {delegates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
