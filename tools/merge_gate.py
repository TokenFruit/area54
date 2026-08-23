"""Decide whether a pull request may be merged, in code rather than in judgement.

The merge is the one irreversible step, and until now it was gated by an agent
reading its own instructions and deciding it was satisfied. A sufficiently
persuasive prompt satisfies that. This does not: it queries GitHub, applies the
rules, and exits non-zero when any of them fails.

On success it writes a short-lived authorisation naming the PR and the exact
head SHA. The shell guard permits `gh pr merge` only when a valid authorisation
matches, so an agent cannot merge by concluding it is allowed to — only by
having actually passed.

    python -m tools.merge_gate 8 --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: How long an authorisation stays valid. Long enough to merge, short enough
#: that one cannot sit around authorising a later, different merge.
TOKEN_TTL_SECONDS = 10 * 60

TOKEN_DIR = ".claude"
TOKEN_NAME = "merge-authorisation.json"

#: A Lead verdict. Prose is matched loosely on purpose: what is pinned is the
#: presence of a verdict, not its wording.
LEAD_APPROVE = re.compile(r"\bverdict\b.{0,40}\bapprove\b", re.IGNORECASE | re.DOTALL)
LEAD_REJECT = re.compile(r"\bchanges requested\b", re.IGNORECASE)
LEAD_COUNTS = re.compile(r"(\d+)\s+blockers?|(\d+)\s+majors?", re.IGNORECASE)

#: A Tester verdict. Its absence is the failure this gate exists to catch: on
#: TF-002 the Tester passed and reported into a transcript, so the merged change
#: carried a code review and no evidence anyone had verified it against a spec.
TESTER_VERDICT = re.compile(
    r"\btester\b.{0,200}?\bverdict\b.{0,40}?\b(pass|fail)\b", re.IGNORECASE | re.DOTALL
)


#: The CPO's waiver, in place of a spec link: a PR body may state
#: `No spec: <reason>`. Named so the orchestrator reads the waiver the same way.
NO_SPEC_WAIVER = re.compile(r"^No spec: .+", re.MULTILINE)


class GateError(Exception):
    """The gate could not be evaluated. Never treated as a pass."""


@dataclass(frozen=True)
class Result:
    """One rule's outcome."""

    name: str
    passed: bool
    detail: str


def _gh(args: list[str]) -> str:
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)  # noqa: S603
    except FileNotFoundError as exc:
        raise GateError("the gh CLI is not installed; the gate cannot be evaluated.") from exc
    except subprocess.CalledProcessError as exc:
        raise GateError(f"gh {' '.join(args)} failed: {exc.stderr.strip()[:200]}") from exc
    return done.stdout


def fetch(pr: int, repo: str) -> dict[str, object]:
    """Return everything the rules need, in one request set."""
    fields = "number,headRefOid,isDraft,mergeable,body,statusCheckRollup"
    data: dict[str, object] = json.loads(
        _gh(["pr", "view", str(pr), "--repo", repo, "--json", fields])
    )
    comments = json.loads(_gh(["api", f"repos/{repo}/issues/{pr}/comments"]))
    reviews = json.loads(_gh(["api", f"repos/{repo}/pulls/{pr}/reviews"]))
    data["all_comments"] = [str(c.get("body", "")) for c in comments] + [
        str(r.get("body", "")) for r in reviews
    ]
    return data


def _bodies(data: dict[str, object]) -> list[str]:
    raw = data.get("all_comments", [])
    return [b for b in raw if isinstance(b, str)] if isinstance(raw, list) else []


def check_not_draft(data: dict[str, object]) -> Result:
    draft = bool(data.get("isDraft"))
    return Result("not a draft", not draft, "draft" if draft else "ready for review")


def check_mergeable(data: dict[str, object]) -> Result:
    state = str(data.get("mergeable", ""))
    return Result("mergeable", state == "MERGEABLE", f"mergeable={state or 'unknown'}")


def check_ci_green(data: dict[str, object]) -> Result:
    """Every reported check must have concluded successfully on this head."""
    rollup = data.get("statusCheckRollup")
    if not isinstance(rollup, list) or not rollup:
        return Result("CI green", False, "no checks reported — absence is not a pass")
    bad = [
        f"{c.get('name') or c.get('context')}={c.get('conclusion') or c.get('state')}"
        for c in rollup
        if isinstance(c, dict)
        and str(c.get("conclusion") or c.get("state", "")).upper() not in {"SUCCESS", "NEUTRAL"}
    ]
    if bad:
        return Result("CI green", False, ", ".join(bad))
    return Result("CI green", True, f"{len(rollup)} check(s) successful")


def check_spec_linked(data: dict[str, object]) -> Result:
    body = str(data.get("body", ""))
    if "docs/specs/" in body or NO_SPEC_WAIVER.search(body):
        return Result("spec linked", True, "spec linked, or waiver stated")
    return Result("spec linked", False, "no spec link and no 'No spec:' waiver")


def check_lead_verdict(data: dict[str, object]) -> Result:
    """A Lead verdict must exist, approve, and carry no blockers or majors."""
    verdicts = [b for b in _bodies(data) if LEAD_APPROVE.search(b) or LEAD_REJECT.search(b)]
    if not verdicts:
        return Result("lead verdict", False, "no Lead verdict posted to the PR")
    latest = verdicts[-1]
    if LEAD_REJECT.search(latest) and not LEAD_APPROVE.search(latest):
        return Result("lead verdict", False, "latest Lead verdict requests changes")
    for match in LEAD_COUNTS.finditer(latest):
        count = int(match.group(1) or match.group(2) or 0)
        if count > 0:
            return Result("lead verdict", False, f"Lead reports {match.group(0)}")
    return Result("lead verdict", True, "Lead approved, no blockers or majors")


def check_tester_verdict(data: dict[str, object]) -> Result:
    """A Tester verdict must exist on the PR and say Pass.

    A verdict that lives only in a transcript does not exist as far as this
    gate is concerned. That is the point: the PR is the durable record.
    """
    found = [m for b in _bodies(data) if (m := TESTER_VERDICT.search(b))]
    if not found:
        return Result("tester verdict", False, "no Tester verdict posted to the PR")
    latest = found[-1].group(1).lower()
    return Result("tester verdict", latest == "pass", f"Tester verdict: {latest}")


RULES = (
    check_not_draft,
    check_mergeable,
    check_ci_green,
    check_spec_linked,
    check_lead_verdict,
    check_tester_verdict,
)


def evaluate(data: dict[str, object]) -> list[Result]:
    """Apply every rule to already-fetched data."""
    return [rule(data) for rule in RULES]


def write_authorisation(pr: int, repo: str, head: str, root: Path) -> Path:
    """Record that this exact PR, at this exact commit, passed just now."""
    path = root / TOKEN_DIR / TOKEN_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pr": pr, "repo": repo, "head": head, "issued": time.time()}),
        encoding="utf-8",
    )
    return path


def read_authorisation(root: Path) -> dict[str, object] | None:
    """Return a valid, unexpired authorisation, or None."""
    path = root / TOKEN_DIR / TOKEN_NAME
    if not path.is_file():
        return None
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(token, dict):
        return None
    try:
        issued = float(token.get("issued", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - issued > TOKEN_TTL_SECONDS:
        return None
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.merge_gate", description=__doc__)
    parser.add_argument("pr", type=int)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--root", default=".", help="where to write the authorisation")
    args = parser.parse_args(argv)

    try:
        data = fetch(args.pr, args.repo)
        results = evaluate(data)
    except GateError as exc:
        print(f"::error::gate could not be evaluated: {exc}")
        print("Refusing. An unevaluated gate is a failed gate.")
        return 1

    for result in results:
        print(f"  [{'PASS' if result.passed else 'FAIL'}] {result.name:18} {result.detail}")

    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\nRefused: {len(failed)} of {len(results)} rules failed.")
        print("Report this to the CPO. Do not merge, and do not work around it.")
        return 1

    head = str(data.get("headRefOid", ""))
    path = write_authorisation(args.pr, args.repo, head, Path(args.root))
    print(f"\nAll {len(results)} rules passed. Authorisation written to {path}")
    print(f"Valid {TOKEN_TTL_SECONDS // 60} minutes, for PR #{args.pr} at {head[:8]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
