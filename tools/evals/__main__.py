"""Run the eval suite.

    python -m tools.evals --list        # show the cases, run nothing
    python -m tools.evals               # live run; needs the claude CLI, costs money

Live runs invoke a model once per trial, so they are deliberately not wired
into the pull-request pipeline. See .github/workflows/evals.yml.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.evals.case import EvalCaseError, load_cases
from tools.evals.report import render, render_github_errors
from tools.evals.runner import ClaudeCliRunner, run_trial
from tools.evals.scoring import CaseResult, score_case, score_trial


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.evals", description=__doc__)
    parser.add_argument("--list", action="store_true", help="list cases without running them")
    parser.add_argument("--case", help="run only the case with this name")
    parser.add_argument("--github", action="store_true", help="emit ::error:: lines for CI")
    parser.add_argument(
        "--save-transcripts",
        metavar="DIR",
        help="write each trial's full output here. Without it, diagnosing a "
        "failure means reproducing the run by hand",
    )
    parser.add_argument(
        "--trials",
        type=int,
        help="override the per-case trial count. Use 1 for a cheap smoke run; "
        "a 1-trial result is not evidence and the report says so",
    )
    args = parser.parse_args(argv)

    try:
        cases = load_cases()
    except EvalCaseError as exc:
        print(f"::error::{exc}")
        return 1

    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            print(f"::error::no eval case named {args.case!r}")
            return 1

    if args.list:
        print(f"{len(cases)} eval case(s):\n")
        for case in cases:
            print(f"  {case.name:42} {case.agent:16} {case.threshold}/{case.trials} trials")
        return 0

    runner = ClaudeCliRunner()
    if not runner.is_available():
        print(
            "::error::the 'claude' CLI is not on PATH, so no live eval can run.\n"
            "Install the Claude Code CLI, then re-run. Use --list to inspect the cases."
        )
        return 1

    results: list[CaseResult] = []
    for case in cases:
        trials = args.trials or case.trials
        if args.trials:
            print(
                f"  running {case.name} {trials}x instead of {case.trials}x — "
                f"a reduced run is a smoke test, not evidence",
                file=sys.stderr,
            )
        outcomes = []
        for trial in range(trials):
            print(f"  {case.name} trial {trial + 1}/{trials}", file=sys.stderr)
            run = run_trial(case, runner)
            outcomes.append(score_trial(case.expect, run.output, run.changed_files, run.exit_code))
            if args.save_transcripts:
                target = Path(args.save_transcripts) / f"{case.name}-{trial + 1}.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(run.output, encoding="utf-8")
        results.append(score_case(case, outcomes))

    print(render(results))
    if args.github:
        errors = render_github_errors(results)
        if errors:
            print(errors)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
