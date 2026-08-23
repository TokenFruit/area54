"""CI entry point: fail the build if any agent definition is invalid."""

from __future__ import annotations

import sys

from tools.agents import AgentDefinitionError, load_agents, validate


def main() -> int:
    try:
        agents = load_agents()
        failures = validate()
    except AgentDefinitionError as exc:
        print(f"::error::{exc}")
        return 1

    if failures:
        for failure in failures:
            print(f"::error::{failure}")
        print(f"\n{len(failures)} problem(s) across {len(agents)} agent definition(s).")
        return 1

    print(f"{len(agents)} agent definitions valid; every model pinned to an exact identifier.")
    for agent in agents:
        print(f"  {agent.name:18} {agent.model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
