"""Tests for the structural check over the constitution's escalation contract.

The check is deliberately blind to wording — TF-019's resolved question 4
forbids pinning prose — so what these tests pin down is the opposite: that it
still fails on a dropped category, and still passes on a section reworded,
reordered, wrapped, or sub-bulleted beyond recognition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.constitution import (
    ConstitutionError,
    check_escalation_lists_are_present_and_long_enough,
    escalation_section,
    subsections,
    top_level_lists,
    validate,
)


def write(path: Path, escalate: int, never: int) -> Path:
    """Write a TEAM.md whose two lists carry the given number of entries."""
    team = path / "TEAM.md"
    team.write_text(
        "# Team\n\n"
        "## Escalation\n\n"
        "Governs unprompted escalation only.\n\n"
        "### Reaches the CPO immediately\n\n"
        + "".join(f"- entry {n}\n" for n in range(escalate))
        + "\n### Never surfaced\n\n"
        + "".join(f"- entry {n}\n" for n in range(never))
        + "\n## What agents must never do\n\n- something else\n",
        encoding="utf-8",
    )
    return team


# --- the shipped constitution ---------------------------------------------


def test_the_constitution_validates() -> None:
    assert validate() == []


# --- the check's two cases -------------------------------------------------


def test_two_full_lists_pass(tmp_path: Path) -> None:
    assert validate(write(tmp_path, escalate=6, never=5)) == []


def test_a_short_escalate_list_fails_and_names_that_list(tmp_path: Path) -> None:
    """Five entries would pass a five-floor. The floor is six for this reason."""
    failures = validate(write(tmp_path, escalate=5, never=5))
    assert len(failures) == 1
    assert "escalate-immediately list needs at least 6" in failures[0]
    assert "has 5 entry(ies)" in failures[0]


def test_a_short_never_surface_list_fails_and_names_that_list(tmp_path: Path) -> None:
    failures = validate(write(tmp_path, escalate=6, never=4))
    assert len(failures) == 1
    assert "never-surface list needs at least 5" in failures[0]


def test_a_failure_names_the_line_of_the_heading_it_is_about(tmp_path: Path) -> None:
    """The message promises a `###` line number, so it has to be the real one."""
    team = write(tmp_path, escalate=6, never=4)
    lines = team.read_text(encoding="utf-8").splitlines()
    expected = lines.index("### Never surfaced") + 1
    assert validate(team)[0].startswith(f"TEAM.md:{expected}:")


def test_a_failure_does_not_claim_the_order_was_checked(tmp_path: Path) -> None:
    """Position is the only discriminator, so the message must not pretend more.

    A swapped pair fails loudly while naming the list it *should* have been,
    and the message has to say so rather than assert a role it cannot know.
    """
    failures = validate(write(tmp_path, escalate=5, never=5))
    assert "told apart by position alone" in failures[0]
    assert "really the never-surface one" in failures[0]


# --- the shape the check requires ------------------------------------------


def test_a_missing_escalation_section_raises(tmp_path: Path) -> None:
    team = tmp_path / "TEAM.md"
    team.write_text("# Team\n\n## Coding standards\n\n- one\n", encoding="utf-8")
    with pytest.raises(ConstitutionError, match="no `## Escalation` section"):
        validate(team)


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConstitutionError, match="constitution not found"):
        validate(tmp_path / "absent.md")


def test_a_third_subsection_is_caught(tmp_path: Path) -> None:
    """Loud, not silent: an extra subsection is a contract nobody agreed to."""
    team = write(tmp_path, escalate=6, never=5)
    team.write_text(
        team.read_text(encoding="utf-8").replace(
            "\n## What agents must never do", "\n### Sometimes\n\n- a third way\n\n## Later"
        ),
        encoding="utf-8",
    )
    failures = validate(team)
    assert len(failures) == 1
    assert "has 3 `###` subsection(s), expected 2" in failures[0]


def test_a_second_list_in_a_subsection_is_caught(tmp_path: Path) -> None:
    """Translations left inside a subsection read as a list, and must not pass."""
    team = write(tmp_path, escalate=6, never=5)
    team.write_text(
        team.read_text(encoding="utf-8").replace(
            "\n## What agents must never do", "\nAlso translate:\n\n- one\n- two\n\n## Later"
        ),
        encoding="utf-8",
    )
    failures = validate(team)
    assert len(failures) == 1
    assert "holds 2 top-level lists" in failures[0]


# --- what the check must survive -------------------------------------------


def test_wrapped_entries_count_once_each() -> None:
    """The repo wraps at 80 columns; a wrapped entry is one entry, not two."""
    body = [
        "- a first entry that runs on",
        "  and continues here",
        "- a second entry",
        "  wrapped as well",
    ]
    assert top_level_lists(body) == [2]


def test_sub_bullets_belong_to_the_entry_above() -> None:
    assert top_level_lists(["- one", "  - detail", "  - more detail", "- two"]) == [2]


def test_an_ordered_list_is_a_list() -> None:
    """Criterion 1 says "a Markdown list", and a numbered list is one."""
    assert top_level_lists(["1. one", "2) two", "3. three"]) == [3]


def test_a_blank_line_alone_does_not_end_a_list() -> None:
    """A loosely-spaced list is one list, not two of one entry each."""
    assert top_level_lists(["- one", "", "- two"]) == [2]


def test_prose_at_column_zero_ends_a_list() -> None:
    assert top_level_lists(["- one", "", "Prose.", "", "- two"]) == [1, 1]


def test_bullets_inside_a_fence_are_examples_not_entries(tmp_path: Path) -> None:
    team = write(tmp_path, escalate=6, never=5)
    team.write_text(
        team.read_text(encoding="utf-8").replace(
            "Governs unprompted escalation only.",
            "Governs unprompted escalation only.\n\n```\n- not an entry\n- nor this\n```",
        ),
        encoding="utf-8",
    )
    assert validate(team) == []


def test_the_section_stops_at_the_next_heading() -> None:
    section = escalation_section("## Escalation\n\n### One\n\n- a\n\n## Next\n\n### Two\n\n- b\n")
    assert [heading for heading, _ in subsections(section)] == [3]


def test_a_heading_that_merely_starts_with_the_word_is_not_the_section() -> None:
    """`## Escalations` is a different section, and checking it checks nothing."""
    with pytest.raises(ConstitutionError, match="no `## Escalation` section"):
        escalation_section("## Escalations\n\n### One\n\n- a\n\n### Two\n\n- b\n")


def test_a_heading_inside_a_fence_does_not_end_the_section(tmp_path: Path) -> None:
    """Documenting the required shape inside the section must not truncate it.

    A fenced `## ` line is an example, exactly as a fenced bullet is. Before
    the fence state was consulted first, this failed with "has 0 `###`
    subsection(s)" on a constitution that was entirely correct.
    """
    team = write(tmp_path, escalate=6, never=5)
    team.write_text(
        team.read_text(encoding="utf-8").replace(
            "Governs unprompted escalation only.",
            "Governs unprompted escalation only. The shape:\n\n"
            "```\n## Escalation\n\n### Reaches the CPO immediately\n\n- one per category\n```",
        ),
        encoding="utf-8",
    )
    assert validate(team) == []


def test_the_check_is_blind_to_wording(tmp_path: Path) -> None:
    """The cost of resolved question 4, stated as a test so nobody forgets it.

    Six bullets of nonsense pass. That is what buys a section that can be
    reworded without touching the validator.
    """
    team = write(tmp_path, escalate=6, never=5)
    team.write_text(
        team.read_text(encoding="utf-8")
        .replace("### Reaches the CPO immediately", "### Ping him")
        .replace("### Never surfaced", "### Keep quiet"),
        encoding="utf-8",
    )
    assert validate(team) == []


def test_the_check_reports_both_lists_at_once(tmp_path: Path) -> None:
    """One run, every failure — the caller prints them all as annotations."""
    team = write(tmp_path, escalate=1, never=1)
    section = escalation_section(team.read_text(encoding="utf-8"))
    assert len(check_escalation_lists_are_present_and_long_enough(subsections(section))) == 2
