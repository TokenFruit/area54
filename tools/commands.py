"""Read and validate the CPO's slash commands.

A command that delegates to an agent which does not exist fails silently: the
command runs, the delegation quietly resolves to nothing, and the CPO gets a
plausible-looking answer produced by no one in particular. These checks make
that a build failure instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.agents import FRONTMATTER, KNOWN_TOOLS, AgentDefinitionError

COMMANDS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "commands"

#: The house convention for delegating: ``**agent-name** subagent``.
#:
#: The check is only as good as the convention, so it is enforced in both
#: directions — see :func:`check_delegation_convention`.
AGENT_REFERENCE = re.compile(r"\*\*([a-z][a-z0-9-]*)\*\*(?=\s+subagent\b)")

#: Any bold lowercase token, used to catch agent names written the wrong way.
BOLD_TOKEN = re.compile(r"\*\*([a-z][a-z0-9-]*)\*\*")


@dataclass(frozen=True)
class Command:
    """One slash command, parsed from its markdown file."""

    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def allowed_tools(self) -> list[str]:
        raw = self.frontmatter.get("allowed-tools", "")
        if isinstance(raw, list):
            return [str(t).strip() for t in raw]
        return [t.strip() for t in str(raw).split(",") if t.strip()]

    @property
    def referenced_agents(self) -> list[str]:
        """Agent names this command delegates to, in the house convention."""
        return sorted(set(AGENT_REFERENCE.findall(self.body)))


def parse_command(path: Path) -> Command:
    """Parse one command file.

    Raises:
        AgentDefinitionError: the file has no frontmatter, or it is not a mapping.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if match is None:
        raise AgentDefinitionError(f"{path.name}: no YAML frontmatter.")
    loaded = yaml.safe_load(match.group(1))
    if not isinstance(loaded, dict):
        raise AgentDefinitionError(f"{path.name}: frontmatter is not a mapping.")
    return Command(path=path, frontmatter=loaded, body=text[match.end() :])


def load_commands(directory: Path = COMMANDS_DIR) -> list[Command]:
    """Parse every command in *directory*, sorted by filename."""
    if not directory.is_dir():
        raise AgentDefinitionError(f"commands directory not found: {directory}")
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise AgentDefinitionError(f"no commands found in {directory}")
    return [parse_command(p) for p in paths]


def check_has_description(command: Command) -> list[str]:
    """A command with no description is invisible in the command list."""
    if not command.frontmatter.get("description"):
        return [f"{command.path.name}: missing 'description' frontmatter."]
    return []


def check_allowed_tools_are_known(command: Command) -> list[str]:
    """Return failures for tool names in ``allowed-tools`` that do not exist."""
    unknown = sorted(set(command.allowed_tools) - KNOWN_TOOLS)
    if unknown:
        return [f"{command.path.name}: unknown tool(s) in allowed-tools: {unknown}."]
    return []


def check_references_resolve(command: Command, agent_names: set[str]) -> list[str]:
    """Return failures for delegations to agents that do not exist."""
    return [
        f"{command.path.name}: delegates to '{ref}', which is not an agent. "
        f"Known agents: {sorted(agent_names)}."
        for ref in command.referenced_agents
        if ref not in agent_names
    ]


def check_delegation_convention(command: Command, agent_names: set[str]) -> list[str]:
    """Return failures where an agent is named outside the house convention.

    Without this the reference check is trivially bypassed: write
    ``**architet**`` with no trailing "subagent" and nothing notices the typo.
    """
    failures = []
    conventional = set(command.referenced_agents)
    for token in set(BOLD_TOKEN.findall(command.body)):
        if token in agent_names and token not in conventional:
            failures.append(
                f"{command.path.name}: names agent '{token}' outside the delegation "
                f"convention. Write '**{token}** subagent' so the reference is checkable."
            )
    if "subagent" in command.body and not conventional:
        failures.append(
            f"{command.path.name}: mentions 'subagent' but delegates to none in the "
            f"convention '**agent-name** subagent'. The reference check cannot see it."
        )
    return failures


def check_no_orphan_agents(commands: list[Command], agent_names: set[str]) -> list[str]:
    """Return a failure for any agent no command ever invokes.

    An agent nothing reaches is dead code, which CLAUDE.md forbids.
    """
    referenced = {ref for c in commands for ref in c.referenced_agents}
    if orphans := sorted(agent_names - referenced):
        return [
            f"agent(s) {orphans} are invoked by no command. Either wire them into a "
            f"command or delete them — CLAUDE.md forbids dead code."
        ]
    return []
