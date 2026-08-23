"""Deterministic checks over the team's agent definitions.

These are the checks that must never be left to a prompt. Everything decidable
by reading a file is decided here, so that a regression fails CI rather than
quietly degrading an agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.agents import (
    FLOATING_ALIASES,
    PINNED_MODELS,
    Agent,
    AgentDefinitionError,
    check_model_is_pinned,
    check_role_tool_policy,
    check_tools_are_known,
    load_agents,
    parse_agent,
    validate,
)

EXPECTED_ROLES = {
    "product-owner",
    "architect",
    "designer",
    "builder-backend",
    "builder-frontend",
    "lead",
    "tester",
    "devops",
}


@pytest.fixture(scope="module")
def agents() -> list[Agent]:
    return load_agents()


def test_every_role_is_present(agents: list[Agent]) -> None:
    assert {a.name for a in agents} == EXPECTED_ROLES


def test_the_whole_team_validates() -> None:
    assert validate() == []


# --- TF-002: model pinning ------------------------------------------------


@pytest.mark.parametrize("agent_name", sorted(EXPECTED_ROLES))
def test_agent_pins_an_exact_model(agents: list[Agent], agent_name: str) -> None:
    """No agent may run on a floating alias.

    An alias resolves to whatever is newest in its family, so a model upgrade
    would change the agent's behaviour with no commit to review, bisect, or
    revert. See ADR-0001, "Risks".
    """
    agent = next(a for a in agents if a.name == agent_name)
    assert agent.model not in FLOATING_ALIASES, f"{agent_name} runs on a floating alias"
    assert agent.model in PINNED_MODELS, f"{agent_name} pins an unknown model: {agent.model}"


def test_a_floating_alias_is_rejected(tmp_path: Path) -> None:
    """The guard must actually fail on the thing it exists to catch."""
    bad = tmp_path / "drifty.md"
    bad.write_text(
        "---\nname: drifty\ndescription: d\ntools: Read\nmodel: opus\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_model_is_pinned(parse_agent(bad))
    assert len(failures) == 1
    assert "floating alias" in failures[0]


def test_a_typo_in_a_model_id_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "typo.md"
    bad.write_text(
        "---\nname: typo\ndescription: d\ntools: Read\nmodel: claude-opus-55\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_model_is_pinned(parse_agent(bad))
    assert len(failures) == 1
    assert "not a known pinned identifier" in failures[0]


def test_a_missing_model_field_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "nomodel.md"
    bad.write_text(
        "---\nname: nomodel\ndescription: d\ntools: Read\n---\n\nbody\n", encoding="utf-8"
    )
    failures = check_model_is_pinned(parse_agent(bad))
    assert len(failures) == 1
    assert "no 'model' field" in failures[0]


# --- structural invariants ------------------------------------------------


def test_every_agent_declares_scoped_tools(agents: list[Agent]) -> None:
    """An agent with no explicit tools list inherits everything."""
    for agent in agents:
        assert agent.tools, f"{agent.name} declares no tools"


def test_the_lead_cannot_write(agents: list[Agent]) -> None:
    """The invariant the review gate rests on.

    A reviewer that can edit stops reporting findings and starts silently
    patching them, and the CPO loses all visibility into code quality.
    """
    lead = next(a for a in agents if a.name == "lead")
    forbidden = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
    assert not forbidden & set(lead.tools), (
        f"lead has write tools: {sorted(forbidden & set(lead.tools))}"
    )


def test_malformed_frontmatter_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "broken.md"
    bad.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(AgentDefinitionError, match="no YAML frontmatter"):
        parse_agent(bad)


# --- TF-004: tool scoping -------------------------------------------------


def test_every_tool_name_is_real(agents: list[Agent]) -> None:
    """A misspelt tool grants nothing and fails at runtime, silently."""
    for agent in agents:
        assert check_tools_are_known(agent) == []


def test_every_role_holds_exactly_what_its_job_needs(agents: list[Agent]) -> None:
    for agent in agents:
        assert check_role_tool_policy(agent) == []


def test_giving_the_lead_a_write_tool_is_caught(tmp_path: Path) -> None:
    """The separation the review gate depends on."""
    bad = tmp_path / "lead.md"
    bad.write_text(
        "---\nname: lead\ndescription: d\ntools: Read, Grep, Bash, Edit\n"
        "model: claude-opus-5\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_role_tool_policy(parse_agent(bad))
    assert any("forbidden tool(s) ['Edit']" in f for f in failures)


def test_giving_the_product_owner_a_shell_is_caught(tmp_path: Path) -> None:
    bad = tmp_path / "product-owner.md"
    bad.write_text(
        "---\nname: product-owner\ndescription: d\ntools: Read, Write, Bash\n"
        "model: claude-opus-5\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_role_tool_policy(parse_agent(bad))
    assert any("forbidden tool(s) ['Bash']" in f for f in failures)


def test_taking_the_shell_from_a_builder_is_caught(tmp_path: Path) -> None:
    """A Builder that cannot run its own tests cannot meet the Definition of Done."""
    bad = tmp_path / "builder-backend.md"
    bad.write_text(
        "---\nname: builder-backend\ndescription: d\ntools: Read, Write, Edit\n"
        "model: claude-opus-5\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_role_tool_policy(parse_agent(bad))
    assert any("missing required tool(s) ['Bash']" in f for f in failures)


def test_a_misspelt_tool_is_caught(tmp_path: Path) -> None:
    bad = tmp_path / "typo.md"
    bad.write_text(
        "---\nname: typo\ndescription: d\ntools: Read, Grepp\nmodel: claude-opus-5\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_tools_are_known(parse_agent(bad))
    assert len(failures) == 1
    assert "Grepp" in failures[0]


def test_a_new_role_without_a_policy_is_caught(tmp_path: Path) -> None:
    """Adding an agent must not silently skip tool checking."""
    bad = tmp_path / "newcomer.md"
    bad.write_text(
        "---\nname: newcomer\ndescription: d\ntools: Read, Bash\n"
        "model: claude-opus-5\n---\n\nbody\n",
        encoding="utf-8",
    )
    failures = check_role_tool_policy(parse_agent(bad))
    assert len(failures) == 1
    assert "no tool policy" in failures[0]
