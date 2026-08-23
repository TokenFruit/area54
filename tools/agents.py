"""Read and validate the team's agent definitions.

area54 ships prompts, not a running service, so the usual safety net of a type
checker and a test suite does not reach most of what can go wrong. These checks
cover the part that *is* mechanically decidable: that every agent declares who
it is, what it may touch, and — the subject of TF-002 — exactly which model it
runs on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"

#: Model identifiers an agent may pin to. Each names one model.
PINNED_MODELS = frozenset(
    {
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-haiku-4-5-20251001",
    }
)

#: Aliases that resolve to whatever is newest in their family. Banned in agent
#: definitions: an alias lets a model upgrade change every agent's behaviour
#: with nothing in git to review, bisect, or roll back. See ADR-0001, "Risks".
FLOATING_ALIASES = frozenset({"opus", "sonnet", "haiku", "default", "inherit"})

REQUIRED_FIELDS = ("name", "description", "tools", "model")

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


class AgentDefinitionError(Exception):
    """An agent definition is malformed or violates a team invariant."""


@dataclass(frozen=True)
class Agent:
    """One agent definition, parsed from its markdown file."""

    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def name(self) -> str:
        return str(self.frontmatter.get("name", ""))

    @property
    def model(self) -> str:
        return str(self.frontmatter.get("model", ""))

    @property
    def tools(self) -> list[str]:
        raw = self.frontmatter.get("tools", "")
        if isinstance(raw, list):
            return [str(t).strip() for t in raw]
        return [t.strip() for t in str(raw).split(",") if t.strip()]


def parse_agent(path: Path) -> Agent:
    """Parse one agent definition file.

    Raises:
        AgentDefinitionError: the file has no frontmatter, or it is not a mapping.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if match is None:
        raise AgentDefinitionError(
            f"{path.name}: no YAML frontmatter. The file must open with a --- delimited block."
        )
    loaded = yaml.safe_load(match.group(1))
    if not isinstance(loaded, dict):
        raise AgentDefinitionError(f"{path.name}: frontmatter is not a mapping.")
    return Agent(path=path, frontmatter=loaded, body=text[match.end() :])


def load_agents(directory: Path = AGENTS_DIR) -> list[Agent]:
    """Parse every agent definition in *directory*, sorted by filename."""
    if not directory.is_dir():
        raise AgentDefinitionError(f"agents directory not found: {directory}")
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise AgentDefinitionError(f"no agent definitions found in {directory}")
    return [parse_agent(p) for p in paths]


def check_model_is_pinned(agent: Agent) -> list[str]:
    """Return the reasons *agent* fails the TF-002 model-pinning rule."""
    model = agent.model
    if not model:
        return [f"{agent.path.name}: no 'model' field. Pin one of {sorted(PINNED_MODELS)}."]
    if model in FLOATING_ALIASES:
        return [
            f"{agent.path.name}: model '{model}' is a floating alias. A model upgrade would "
            f"change this agent with no commit to review or revert. "
            f"Pin one of {sorted(PINNED_MODELS)}."
        ]
    if model not in PINNED_MODELS:
        return [
            f"{agent.path.name}: model '{model}' is not a known pinned identifier. "
            f"Add it to PINNED_MODELS if it is real, or correct the typo."
        ]
    return []


def check_required_fields(agent: Agent) -> list[str]:
    """Return the reasons *agent* is missing required frontmatter fields."""
    missing = [f for f in REQUIRED_FIELDS if not agent.frontmatter.get(f)]
    if missing:
        return [f"{agent.path.name}: missing required frontmatter: {', '.join(missing)}."]
    return []


def check_name_matches_filename(agent: Agent) -> list[str]:
    """Return a failure if the declared name does not match the filename.

    A mismatch means slash commands that delegate by name silently fail to
    resolve the agent they meant.
    """
    expected = agent.path.stem
    if agent.name != expected:
        return [f"{agent.path.name}: declares name '{agent.name}', expected '{expected}'."]
    return []


def validate(directory: Path = AGENTS_DIR) -> list[str]:
    """Run every check over every agent. Returns all failures."""
    agents = load_agents(directory)
    failures: list[str] = []
    for agent in agents:
        failures += check_required_fields(agent)
        failures += check_model_is_pinned(agent)
        failures += check_name_matches_filename(agent)
        failures += check_tools_are_known(agent)
        failures += check_role_tool_policy(agent)
    return failures


#: Every tool an agent or command may name. A typo like "Grepp" silently grants
#: nothing, and the agent fails at runtime in a way no reader would predict, so
#: unknown names are rejected here. Add real tools as they appear.
KNOWN_TOOLS = frozenset(
    {
        "Agent",
        "Artifact",
        "Bash",
        "BashOutput",
        "Edit",
        "Glob",
        "Grep",
        "KillShell",
        "NotebookEdit",
        "Read",
        "SlashCommand",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)

#: Tools that mutate files. The Lead must hold none of them.
WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


@dataclass(frozen=True)
class RolePolicy:
    """The tool ceiling and floor for one role.

    ``required`` is what the role cannot do its job without. ``forbidden`` is
    what it must never hold — the separations the team's design depends on.
    """

    required: frozenset[str]
    forbidden: frozenset[str]
    reason: str


#: Which tools each role may and must hold.
#:
#: These encode separations that were previously only asserted in prose, where
#: nothing checked them and they could quietly stop being true.
ROLE_POLICY: dict[str, RolePolicy] = {
    "product-owner": RolePolicy(
        required=frozenset({"Read", "Write"}),
        forbidden=frozenset({"Bash", "Edit", "NotebookEdit"}),
        reason="The PO defines what must be true, and never runs or edits code.",
    ),
    "architect": RolePolicy(
        required=frozenset({"Read", "Write", "Grep"}),
        forbidden=frozenset({"NotebookEdit"}),
        reason="The Architect reads the codebase and writes ADRs, and must be able "
        "to update CLAUDE.md's Stack and Commands tables.",
    ),
    "designer": RolePolicy(
        required=frozenset({"Read", "Write"}),
        forbidden=frozenset({"Bash", "Edit", "NotebookEdit"}),
        reason="The Designer produces documents, not code, and has no reason to execute anything.",
    ),
    "builder-backend": RolePolicy(
        required=frozenset({"Read", "Write", "Edit", "Bash"}),
        forbidden=frozenset(),
        reason="Builders implement, and must be able to run their own tests.",
    ),
    "builder-frontend": RolePolicy(
        required=frozenset({"Read", "Write", "Edit", "Bash"}),
        forbidden=frozenset(),
        reason="Builders implement, and must be able to run their own tests.",
    ),
    "lead": RolePolicy(
        required=frozenset({"Read", "Grep", "Bash"}),
        forbidden=WRITE_TOOLS,
        reason="A reviewer that can edit stops reporting findings and starts "
        "silently patching them. The whole review gate rests on this.",
    ),
    "tester": RolePolicy(
        required=frozenset({"Read", "Write", "Edit", "Bash"}),
        forbidden=frozenset(),
        reason="The Tester writes tests and runs the suite.",
    ),
    "devops": RolePolicy(
        required=frozenset({"Read", "Bash"}),
        forbidden=frozenset(),
        reason="DevOps drives the pipeline through the shell.",
    ),
}


def check_tools_are_known(agent: Agent) -> list[str]:
    """Return failures for tool names that do not exist."""
    unknown = sorted(set(agent.tools) - KNOWN_TOOLS)
    if unknown:
        return [
            f"{agent.path.name}: unknown tool(s) {unknown}. A misspelt tool grants nothing "
            f"and fails at runtime. Add to KNOWN_TOOLS if real, or fix the typo."
        ]
    return []


def check_role_tool_policy(agent: Agent) -> list[str]:
    """Return failures where *agent* holds too much, or too little, for its role."""
    policy = ROLE_POLICY.get(agent.name)
    if policy is None:
        return [
            f"{agent.path.name}: no tool policy for role '{agent.name}'. "
            f"Add one to ROLE_POLICY so its tool grants are checked."
        ]
    held = set(agent.tools)
    failures = []
    if granted := sorted(held & policy.forbidden):
        failures.append(f"{agent.path.name}: holds forbidden tool(s) {granted}. {policy.reason}")
    if missing := sorted(policy.required - held):
        failures.append(f"{agent.path.name}: missing required tool(s) {missing}. {policy.reason}")
    return failures
