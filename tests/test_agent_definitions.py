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
    MUNGED,
    PINNED_MODELS,
    SEQUENCE,
    Agent,
    AgentDefinitionError,
    check_closes_by_naming_its_final_message,
    check_declares_its_place_in_the_sequence,
    check_model_is_pinned,
    check_role_tool_policy,
    check_states_its_stop_conditions,
    check_tools_are_known,
    cli_invocation,
    load_agents,
    parse_agent,
    session_flags,
    session_id,
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


# --- the sequence ---------------------------------------------------------


def test_every_agent_knows_what_comes_after_it(agents: list[Agent]) -> None:
    """An agent that cannot name its successor stops and waits for a human."""
    for agent in agents:
        assert check_declares_its_place_in_the_sequence(agent) == []


def test_the_sequence_covers_exactly_the_roles_that_exist(agents: list[Agent]) -> None:
    assert set(SEQUENCE) == {a.name for a in agents}


def test_every_successor_is_a_real_agent(agents: list[Agent]) -> None:
    names = {a.name for a in agents}
    for role, successors in SEQUENCE.items():
        for successor in successors:
            assert successor in names, f"{role} hands off to '{successor}', which does not exist"


def test_devops_is_the_only_terminal_role() -> None:
    """Anything else with no successor is a dead end nobody notices."""
    terminal = [r for r, s in SEQUENCE.items() if not s]
    assert terminal == ["devops"]


def test_an_agent_missing_its_sequence_section_is_caught(tmp_path: Path) -> None:
    bad = tmp_path / "lead.md"
    bad.write_text(
        "---\nname: lead\ndescription: d\ntools: Read, Grep, Bash\n"
        "model: claude-opus-5\n---\n\nno sequence here\n",
        encoding="utf-8",
    )
    failures = check_declares_its_place_in_the_sequence(parse_agent(bad))
    assert len(failures) == 1
    assert "no '## Where you sit in the sequence' section" in failures[0]


# --- TF-019: stop conditions and the closing line -------------------------


def _definition(tmp_path: Path, body: str) -> Agent:
    path = tmp_path / "lead.md"
    path.write_text(
        "---\nname: lead\ndescription: d\ntools: Read, Grep, Bash\n"
        f"model: claude-opus-5\n---\n{body}",
        encoding="utf-8",
    )
    return parse_agent(path)


def test_every_agent_states_its_stop_conditions(agents: list[Agent]) -> None:
    """Criterion 7: without them an agent works a problem until it runs dry."""
    for agent in agents:
        assert check_states_its_stop_conditions(agent) == []


def test_an_agent_missing_its_stop_conditions_is_caught(tmp_path: Path) -> None:
    agent = _definition(tmp_path, "\nno stop conditions here\n\nYour final message: a verdict.\n")
    failures = check_states_its_stop_conditions(agent)
    assert len(failures) == 1
    assert "lead.md: no '## Stop conditions' section" in failures[0]


def test_every_agent_closes_by_naming_its_final_message(agents: list[Agent]) -> None:
    """Criterion 7: the handoff is the last paragraph, in one recognisable form."""
    for agent in agents:
        assert check_closes_by_naming_its_final_message(agent) == []


def test_an_agent_that_never_names_its_final_message_is_caught(tmp_path: Path) -> None:
    agent = _definition(tmp_path, "\n## Stop conditions\n\nStop when stuck.\n")
    failures = check_closes_by_naming_its_final_message(agent)
    assert len(failures) == 1
    assert "does not close with a 'Your final message:' line" in failures[0]


def test_naming_a_final_message_mid_file_is_not_a_closing_line(tmp_path: Path) -> None:
    """The looser substring test `product-owner.md:26` would have satisfied."""
    agent = _definition(
        tmp_path,
        "\n## Stop conditions\n\nName the spec path in your final message: it is the handoff.\n\n"
        "Then go and do something else entirely.\n",
    )
    assert len(check_closes_by_naming_its_final_message(agent)) == 1


# --- session continuity (TF-022) ---------------------------------------------


def _touch_transcript(store: Path, cwd: Path, session: str) -> None:
    """Write the session file the CLI would have written for *cwd*."""
    directory = store / MUNGED.sub("-", str(cwd.resolve()))
    directory.mkdir(parents=True)
    (directory / f"{session}.jsonl").write_text("{}\n", encoding="utf-8")


def test_the_same_role_on_the_same_item_derives_the_same_session() -> None:
    """The whole design rests on this: derived, so nothing has to store it."""
    first = session_id("your-org/area54", "TF-019", "lead")
    assert first == session_id("your-org/area54", "TF-019", "lead")


@pytest.mark.parametrize(
    "other",
    [
        ("your-org/other-repo", "TF-019", "lead"),
        ("your-org/area54", "TF-021", "lead"),
        ("your-org/area54", "TF-019", "tester"),
    ],
)
def test_a_different_repo_item_or_role_derives_a_different_session(
    other: tuple[str, str, str],
) -> None:
    """A Lead resuming the Tester's conversation would read its own review back."""
    assert session_id("your-org/area54", "TF-019", "lead") != session_id(*other)


def test_a_session_the_cli_has_never_seen_is_started(tmp_path: Path) -> None:
    """`--resume` on an unknown id exits 1, so the first round must create."""
    session = session_id("your-org/area54", "TF-019", "lead")
    assert session_flags(session, tmp_path, store=tmp_path / "store") == ["--session-id", session]


def test_a_session_the_cli_already_has_is_resumed(tmp_path: Path) -> None:
    """`--session-id` on a known id exits 1, so later rounds must resume."""
    store, cwd = tmp_path / "store", tmp_path / "repo"
    cwd.mkdir()
    session = session_id("your-org/area54", "TF-019", "lead")
    _touch_transcript(store, cwd, session)
    assert session_flags(session, cwd, store=store) == ["--resume", session]


def test_a_session_from_another_directory_is_not_resumed(tmp_path: Path) -> None:
    """The store is keyed by cwd: the same id elsewhere is a different conversation."""
    store, cwd, elsewhere = tmp_path / "store", tmp_path / "repo", tmp_path / "other"
    cwd.mkdir()
    elsewhere.mkdir()
    session = session_id("your-org/area54", "TF-019", "lead")
    _touch_transcript(store, elsewhere, session)
    assert session_flags(session, cwd, store=store) == ["--session-id", session]


def test_an_invocation_without_a_session_is_unchanged(agents: list[Agent]) -> None:
    """The eval runner's trials are cold starts by design, for all eight roles."""
    for agent in agents:
        assert cli_invocation(agent, "go") == cli_invocation(agent, "go", session=None)
        assert "--session-id" not in cli_invocation(agent, "go")
        assert "--resume" not in cli_invocation(agent, "go")


def test_an_invocation_with_a_session_appends_the_flags(tmp_path: Path) -> None:
    """Appended, so everything the default path emits stays where it was."""
    agent = _definition(
        tmp_path, "\n## Stop conditions\n\nStop.\n\nYour final message: a verdict.\n"
    )
    cold = cli_invocation(agent, "go", session="s", cwd=tmp_path)
    assert cold[:-2] == cli_invocation(agent, "go")
    assert cold[-2:] == ["--session-id", "s"]
