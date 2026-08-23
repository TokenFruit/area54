"""Score one trial, and aggregate trials into a verdict."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tools.evals.case import EvalCase, Expectation


@dataclass(frozen=True)
class TrialOutcome:
    """What one run of one case produced."""

    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    """The verdict on one case, over all its trials."""

    case: EvalCase
    outcomes: tuple[TrialOutcome, ...]

    @property
    def successes(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def passed(self) -> bool:
        return self.successes >= self.case.threshold

    @property
    def summary(self) -> str:
        return f"{self.successes}/{len(self.outcomes)} (need {self.case.threshold})"

    @property
    def failure_reasons(self) -> list[str]:
        """Distinct reasons across failing trials, most common first."""
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            for reason in outcome.reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return [r for r, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def _found(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None


def score_trial(
    expect: Expectation,
    output: str,
    changed_files: frozenset[str] = frozenset(),
) -> TrialOutcome:
    """Score one trial's output against *expect*.

    Args:
        expect: what the agent was supposed to do.
        output: everything the agent said.
        changed_files: paths, relative to the fixture, the agent modified.
    """
    reasons: list[str] = []

    for pattern in expect.mentions:
        if not _found(pattern, output):
            reasons.append(f"did not mention {pattern!r}")

    if expect.mentions_any and not any(_found(p, output) for p in expect.mentions_any):
        reasons.append(f"mentioned none of {list(expect.mentions_any)}")

    for pattern in expect.forbids:
        if _found(pattern, output):
            reasons.append(f"said {pattern!r}, which it must not")

    for path in expect.files_unchanged:
        if path in changed_files:
            reasons.append(f"modified {path}, which it must leave alone")

    return TrialOutcome(passed=not reasons, reasons=tuple(reasons))


def score_case(case: EvalCase, outcomes: list[TrialOutcome]) -> CaseResult:
    """Aggregate trial outcomes into a case verdict."""
    return CaseResult(case=case, outcomes=tuple(outcomes))
