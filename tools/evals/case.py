"""The eval case format, and loading it from YAML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CASES_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "cases"
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "fixtures"


class EvalCaseError(Exception):
    """An eval case is malformed."""


@dataclass(frozen=True)
class Expectation:
    """What an agent's output must, and must not, contain.

    Patterns are case-insensitive regular expressions. They are deliberately
    loose: an agent's prose varies between runs, so asserting on exact wording
    would measure phrasing rather than behaviour.
    """

    #: Every pattern must appear.
    mentions: tuple[str, ...] = ()
    #: At least one pattern must appear. Use for "any of these phrasings will do".
    mentions_any: tuple[str, ...] = ()
    #: No pattern may appear.
    forbids: tuple[str, ...] = ()
    #: Files that must be byte-identical after the run.
    #:
    #: A strong signal, because it does not depend on what the agent *said*. A
    #: Lead that edits the code has failed regardless of how good its review
    #: reads. Use it only where *any* change is wrong — for an agent whose job
    #: includes writing to the file, prefer :attr:`file_contains`.
    files_unchanged: tuple[str, ...] = ()

    #: ``{path: (pattern, ...)}`` — each pattern must appear in that file after
    #: the run.
    #:
    #: This is how you check that something specific *survived*, rather than
    #: that nothing changed. Asserting the original assertion is still present
    #: catches a weakened test while still allowing the Tester to add new ones,
    #: which is its actual job.
    file_contains: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class EvalCase:
    """One behavioural question, asked of one agent, several times."""

    name: str
    agent: str
    fixture: str
    prompt: str
    expect: Expectation
    #: How many times to run. Evals are stochastic; one trial proves nothing.
    trials: int = 5
    #: How many trials must pass for the case to pass.
    threshold: int = 3
    #: Why this case exists. Printed on failure, so a red eval explains itself.
    rationale: str = ""
    path: Path | None = field(default=None, compare=False)

    @property
    def fixture_dir(self) -> Path:
        return FIXTURES_DIR / self.fixture


def _as_tuple(value: Any, field_name: str, case_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    raise EvalCaseError(f"{case_name}: '{field_name}' must be a string or a list.")


def _parse_file_map(raw: Any, case_name: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise EvalCaseError(f"{case_name}: 'file_contains' must be a mapping of path to patterns.")
    return tuple(
        (str(path), _as_tuple(patterns, f"file_contains[{path}]", case_name))
        for path, patterns in raw.items()
    )


def _parse_expectation(raw: Any, case_name: str) -> Expectation:
    if raw is None:
        raise EvalCaseError(f"{case_name}: no 'expect' block. A case that asserts nothing passes.")
    if not isinstance(raw, dict):
        raise EvalCaseError(f"{case_name}: 'expect' must be a mapping.")
    expectation = Expectation(
        mentions=_as_tuple(raw.get("mentions"), "mentions", case_name),
        mentions_any=_as_tuple(raw.get("mentions_any"), "mentions_any", case_name),
        forbids=_as_tuple(raw.get("forbids"), "forbids", case_name),
        files_unchanged=_as_tuple(raw.get("files_unchanged"), "files_unchanged", case_name),
        file_contains=_parse_file_map(raw.get("file_contains"), case_name),
    )
    if not any(
        [
            expectation.mentions,
            expectation.mentions_any,
            expectation.forbids,
            expectation.files_unchanged,
            expectation.file_contains,
        ]
    ):
        raise EvalCaseError(f"{case_name}: 'expect' is empty. A case that asserts nothing passes.")
    groups = [expectation.mentions, expectation.mentions_any, expectation.forbids]
    groups += [patterns for _, patterns in expectation.file_contains]
    for group in groups:
        for pattern in group:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise EvalCaseError(f"{case_name}: bad regex {pattern!r}: {exc}") from exc
    return expectation


def parse_case(path: Path) -> EvalCase:
    """Parse one eval case file.

    Raises:
        EvalCaseError: the case is malformed, or asserts nothing.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalCaseError(f"{path.name}: not a mapping.")
    name = str(raw.get("name") or path.stem)
    for required in ("agent", "fixture", "prompt"):
        if not raw.get(required):
            raise EvalCaseError(f"{name}: missing '{required}'.")
    trials = int(raw.get("trials", 5))
    threshold = int(raw.get("threshold", 3))
    if trials < 1:
        raise EvalCaseError(f"{name}: trials must be at least 1.")
    if not 1 <= threshold <= trials:
        raise EvalCaseError(f"{name}: threshold {threshold} is not within 1..{trials}.")
    return EvalCase(
        name=name,
        agent=str(raw["agent"]),
        fixture=str(raw["fixture"]),
        prompt=str(raw["prompt"]),
        expect=_parse_expectation(raw.get("expect"), name),
        trials=trials,
        threshold=threshold,
        rationale=str(raw.get("rationale", "")),
        path=path,
    )


def load_cases(directory: Path = CASES_DIR) -> list[EvalCase]:
    """Parse every eval case in *directory*, sorted by filename."""
    if not directory.is_dir():
        raise EvalCaseError(f"eval cases directory not found: {directory}")
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise EvalCaseError(f"no eval cases found in {directory}")
    return [parse_case(p) for p in paths]
