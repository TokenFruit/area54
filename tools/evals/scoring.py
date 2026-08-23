"""Score one trial, and aggregate trials into a verdict."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from tools.evals.case import EvalCase, Expectation


@dataclass(frozen=True)
class TrialOutcome:
    """What one run of one case produced.

    ``errored`` means the run never really happened — an expired login, a
    timeout, a crash. It is kept apart from ``passed`` because a run that did
    not happen is not evidence of anything, and counting it as a behavioural
    failure would make infrastructure problems look like agent regressions.
    """

    passed: bool
    reasons: tuple[str, ...]
    errored: bool = False


@dataclass(frozen=True)
class CaseResult:
    """The verdict on one case, over all its trials."""

    case: EvalCase
    outcomes: tuple[TrialOutcome, ...]

    @property
    def successes(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.errored)

    @property
    def scored(self) -> int:
        """Trials that actually ran, and so can be scored."""
        return len(self.outcomes) - self.errors

    @property
    def inconclusive(self) -> bool:
        """Too few trials completed for the verdict to mean anything."""
        return self.scored < self.required

    @property
    def required(self) -> int:
        """Successes needed, scaled if fewer trials ran than the case asks for."""
        if len(self.outcomes) >= self.case.trials:
            return self.case.threshold
        ratio = self.case.threshold / self.case.trials
        return max(1, math.ceil(len(self.outcomes) * ratio))

    @property
    def passed(self) -> bool:
        return not self.inconclusive and self.successes >= self.required

    @property
    def summary(self) -> str:
        base = f"{self.successes}/{self.scored} (need {self.required})"
        if self.errors:
            base += f", {self.errors} errored"
        return base

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
    exit_code: int = 0,
    files: Mapping[str, str] | None = None,
) -> TrialOutcome:
    """Score one trial's output against *expect*.

    A non-zero *exit_code* means the run failed rather than the agent, so the
    trial is marked errored and no assertion is applied to output that the
    agent never produced.

    Args:
        expect: what the agent was supposed to do.
        output: everything the agent said.
        changed_files: paths, relative to the fixture, the agent modified.
        exit_code: the runner's exit status.
        files: text files left in the workdir, keyed by relative path.
    """
    if exit_code != 0:
        first_line = output.strip().splitlines()[0] if output.strip() else "no output"
        return TrialOutcome(
            passed=False,
            reasons=(f"the run failed (exit {exit_code}): {first_line}",),
            errored=True,
        )

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

    present = files or {}
    for path, patterns in expect.file_contains:
        content = present.get(path)
        if content is None:
            reasons.append(f"{path} does not exist after the run")
            continue
        for pattern in patterns:
            if not _found(pattern, content):
                reasons.append(f"{path} no longer contains {pattern!r}")

    return TrialOutcome(passed=not reasons, reasons=tuple(reasons))


def score_case(case: EvalCase, outcomes: list[TrialOutcome]) -> CaseResult:
    """Aggregate trial outcomes into a case verdict."""
    return CaseResult(case=case, outcomes=tuple(outcomes))
