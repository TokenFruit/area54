"""Render eval results for a human, and for CI."""

from __future__ import annotations

from tools.evals.scoring import CaseResult


def render(results: list[CaseResult]) -> str:
    """Return a report. Failures explain themselves; passes stay quiet."""
    lines: list[str] = []
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    lines.append(f"{len(passed)}/{len(results)} eval cases passed.\n")

    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"  [{mark}] {result.case.name:42} {result.summary}")

    if failed:
        lines.append("\nFailures:\n")
        for result in failed:
            lines.append(f"  {result.case.name} — {result.summary}")
            if result.case.rationale:
                lines.append(f"    why this case exists: {result.case.rationale}")
            for reason in result.failure_reasons:
                lines.append(f"    - {reason}")
            lines.append("")

    return "\n".join(lines)


def render_github_errors(results: list[CaseResult]) -> str:
    """Return ``::error::`` lines so failures surface in the Actions log."""
    lines = []
    for result in results:
        if not result.passed:
            reasons = "; ".join(result.failure_reasons[:3]) or "no reason recorded"
            lines.append(f"::error::eval '{result.case.name}' failed {result.summary}: {reasons}")
    return "\n".join(lines)
