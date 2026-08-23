"""Check the constitution's escalation contract structurally, never by wording.

`team/TEAM.md` states the escalation contract once: what reaches the CPO
immediately, and what must never be surfaced. Every unenforced rule in this repo
has so far decayed, so the two lists are checked — but only for presence and
length. TF-019's resolved question 4 forbids a check that pins prose: the
section has to stay rewordable without anyone touching this file.

That trade is deliberate and it is worth naming. Six bullets of nonsense pass
here. What does not pass is a category quietly dropped, which is how a closed
list stops being closed — the one failure a structural check can actually see.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEAM_PATH = REPO_ROOT / "team" / "TEAM.md"

#: The only heading text this module pins, and it is matched exactly: a
#: `## Escalations` or `## Escalation contract` is a different section, and
#: taking it for this one would check a contract nobody wrote. The two `###`
#: subsections inside it are identified by position, so their wording stays free.
ESCALATION_HEADING = "## Escalation"

#: Each subsection's list, in the order the subsections must appear, with the
#: number of entries it needs.
#:
#: Each floor is its list's closed-set size — six escalate-immediately
#: categories (TF-019 criterion 2), five never-surface ones (criterion 3). A
#: lower floor would pass a list with a category missing, which is the one thing
#: this check exists to catch.
LIST_FLOORS: tuple[tuple[str, int], ...] = (
    ("escalate-immediately", 6),
    ("never-surface", 5),
)

FENCE = re.compile(r"^\s*(?:```|~~~)")
SUBSECTION = re.compile(r"^### ")
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")


class ConstitutionError(Exception):
    """The constitution is missing, or has no escalation contract to check."""


def escalation_section(text: str) -> list[tuple[int, str]]:
    """Return the `## Escalation` section as ``(line number, line)`` pairs.

    The section runs from its heading to the next `## ` heading or the end of
    the file. Fenced blocks are dropped — a bullet inside a fence is an example,
    not an entry — and because every line carries its own 1-based file line
    number, dropping them renumbers nothing. That is what lets a failure name
    the exact `###` heading it is about.

    Fence state is tracked from the **first line of the file**, and consulted
    before both the heading test and the `## ` break, because a heading inside a
    fence is an example too. Tracking it only after the heading is found is
    worse than not tracking it at all: a fenced sample of the required shape
    placed above the real section — the obvious thing to write, since ADR-0002
    mandates that shape — is taken for the section, and its *closing* fence is
    then read as an opening one, inverting the state for the rest of the file so
    the genuine section is dropped. That combination passes a constitution whose
    lists have decayed to one entry each, which is the single failure this
    module exists to see.

    Raises:
        ConstitutionError: the file has no `## Escalation` section.
    """
    section: list[tuple[int, str]] = []
    found = False
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if not found:
            found = line.strip() == ESCALATION_HEADING
            continue
        if line.startswith("## "):
            break
        section.append((number, line))
    if not found:
        raise ConstitutionError(
            f"TEAM.md: no `{ESCALATION_HEADING}` section. The escalation contract is stated "
            f"once, there, and nine files rely on it existing."
        )
    return section


def subsections(section: list[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    """Split *section* on `### `, discarding the preamble.

    The preamble carries the reporting rule and its translations, which are
    prose and bullets that nothing here should count.
    """
    found: list[tuple[int, list[str]]] = []
    for number, line in section:
        if SUBSECTION.match(line):
            found.append((number, []))
        elif found:
            found[-1][1].append(line)
    return found


def top_level_lists(body: list[str]) -> list[int]:
    """Return the item count of every top-level Markdown list in *body*.

    An item runs to the next item, so an indented sub-bullet and an unindented
    lazy continuation both belong to the item above rather than starting one. A
    list ends only at a blank line followed by a column-0 line that is not an
    item. That is what makes a wrapped seven-item list count as seven, rather
    than as however many runs of bullet lines it happens to break into.
    """
    counts: list[int] = []
    inside = False
    blank = False
    for line in body:
        if LIST_ITEM.match(line):
            if not inside:
                counts.append(0)
                inside = True
            counts[-1] += 1
            blank = False
        elif not line.strip():
            blank = True
        else:
            if inside and blank and not line.startswith((" ", "\t")):
                inside = False
            blank = False
    return counts


def check_escalation_lists_are_present_and_long_enough(
    found: list[tuple[int, list[str]]],
) -> list[str]:
    """Return failures for a contract whose two lists are absent or short.

    Takes the parsed subsections rather than raw lines so that a failure can
    name the `###` heading's real line number in the file.
    """
    if len(found) != len(LIST_FLOORS):
        return [
            f"TEAM.md: `{ESCALATION_HEADING}` has {len(found)} `###` subsection(s), expected "
            f"{len(LIST_FLOORS)} — the escalate-immediately list first, the never-surface list "
            f"second. Everything else in the contract belongs in the preamble above them."
        ]

    failures: list[str] = []
    for index, (role, floor) in enumerate(LIST_FLOORS):
        heading_line, body = found[index]
        counts = top_level_lists(body)
        if len(counts) != 1:
            failures.append(
                f"TEAM.md:{heading_line}: this subsection holds {len(counts)} top-level lists, "
                f"expected exactly 1 — the {role} list. A second list here is usually contract "
                f"prose that belongs in the preamble."
            )
            continue
        if counts[0] < floor:
            other = LIST_FLOORS[1 - index][0]
            failures.append(
                f"TEAM.md:{heading_line}: this subsection's list has {counts[0]} entry(ies); the "
                f"{role} list needs at least {floor}, one per closed-set category. The two "
                f"subsections are told apart by position alone — escalate-immediately first, "
                f"never-surface second — so if this list is really the {other} one, the "
                f"subsections are the wrong way round and that is the fault, not the count."
            )
    return failures


def validate(path: Path = TEAM_PATH) -> list[str]:
    """Run every constitution check. Returns all failures.

    Raises:
        ConstitutionError: the file is missing, or has no `## Escalation`.
    """
    if not path.is_file():
        raise ConstitutionError(f"constitution not found: {path}")
    section = escalation_section(path.read_text(encoding="utf-8"))
    return check_escalation_lists_are_present_and_long_enough(subsections(section))
