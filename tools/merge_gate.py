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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
    fields = "number,headRefOid,isDraft,mergeable,body,statusCheckRollup,commits"
    data: dict[str, object] = json.loads(
        _gh(["pr", "view", str(pr), "--repo", repo, "--json", fields])
    )
    comments = json.loads(_gh(["api", f"repos/{repo}/issues/{pr}/comments"]))
    reviews = json.loads(_gh(["api", f"repos/{repo}/pulls/{pr}/reviews"]))
    data["all_comments"] = [
        {"body": str(c.get("body", "")), "posted": str(c.get("created_at", ""))} for c in comments
    ] + [
        {"body": str(r.get("body", "")), "posted": str(r.get("submitted_at", ""))} for r in reviews
    ]
    data["head_committed_at"] = _head_committed_at(data)
    return data


def _head_committed_at(data: dict[str, object]) -> str:
    """Return the head commit's `committedDate`, matched by SHA rather than position."""
    head = str(data.get("headRefOid", ""))
    commits = data.get("commits")
    if not isinstance(commits, list) or not commits:
        raise GateError("the PR reports no commits; the head commit cannot be dated.")
    for commit in reversed(commits):
        if isinstance(commit, dict) and str(commit.get("oid", "")) == head:
            return str(commit.get("committedDate", ""))
    raise GateError(f"no commit on the PR matches head {head[:8]}; the head cannot be dated.")


def _comments(data: dict[str, object]) -> list[dict[str, object]]:
    raw = data.get("all_comments", [])
    if not isinstance(raw, list):
        raise GateError("the PR comments could not be read; they are not a list.")
    for entry in raw:
        if not isinstance(entry, dict):
            raise GateError(f"a PR comment could not be read; it is a {type(entry).__name__}.")
    return [entry for entry in raw if isinstance(entry, dict)]


def _moment(raw: object, what: str) -> datetime:
    """Parse a GitHub timestamp, refusing anything it cannot compare."""
    if not isinstance(raw, str) or not raw:
        raise GateError(f"{what} carries no timestamp; a verdict cannot be dated without one.")
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"{what} has an unreadable timestamp {raw!r}.") from exc
    if moment.tzinfo is None:
        raise GateError(f"{what} has a timestamp without a zone, {raw!r}; it cannot be compared.")
    return moment


def _verdicts(
    data: dict[str, object], is_verdict: Callable[[str], bool]
) -> tuple[list[str], list[str]]:
    """Split matching verdicts into those covering the head commit, and those predating it.

    A verdict describes the code that existed when it was written, so it counts
    only if it was posted strictly after the head commit was made. This catches
    the sequence the gate used to wave through: approve, push more commits, wait
    for CI to go green, merge code nobody read.

    It does not catch every history rewrite. `committedDate` moves on a rebase
    or an amend, so those are caught; a rewrite that preserves the committer
    date (`--committer-date-is-author-date`, or a force-push of older commits)
    keeps a stale verdict looking current. This rule is about the ordinary
    sequence, not about defeating a determined rewrite.
    """
    head = _moment(data.get("head_committed_at"), "the head commit")
    covering: list[str] = []
    stale: list[str] = []
    for entry in _comments(data):
        body = str(entry.get("body", ""))
        if not is_verdict(body):
            continue
        # Strictly after, so an equal timestamp counts as stale. GitHub stamps
        # to the second, so a verdict sharing the commit's second may have been
        # written just before it — and ambiguous is never a pass here.
        posted = _moment(entry.get("posted"), "a verdict on the PR")
        (covering if posted > head else stale).append(body)
    return covering, stale


def _is_lead_verdict(body: str) -> bool:
    return bool(LEAD_APPROVE.search(body) or LEAD_REJECT.search(body))


def _is_tester_verdict(body: str) -> bool:
    return TESTER_VERDICT.search(body) is not None


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
    if "docs/specs/" in body or re.search(r"^No spec: .+", body, re.MULTILINE):
        return Result("spec linked", True, "spec linked, or waiver stated")
    return Result("spec linked", False, "no spec link and no 'No spec:' waiver")


def check_lead_verdict(data: dict[str, object]) -> Result:
    """A Lead verdict must exist, cover the head, approve, and carry no blockers or majors."""
    covering, stale = _verdicts(data, _is_lead_verdict)
    if not covering:
        if stale:
            return Result(
                "lead verdict", False, "the Lead verdict predates the head commit — re-review it"
            )
        return Result("lead verdict", False, "no Lead verdict posted to the PR")
    latest = covering[-1]
    if LEAD_REJECT.search(latest) and not LEAD_APPROVE.search(latest):
        return Result("lead verdict", False, "latest Lead verdict requests changes")
    for match in LEAD_COUNTS.finditer(latest):
        count = int(match.group(1) or match.group(2) or 0)
        if count > 0:
            return Result("lead verdict", False, f"Lead reports {match.group(0)}")
    return Result("lead verdict", True, "Lead approved, no blockers or majors")


def check_tester_verdict(data: dict[str, object]) -> Result:
    """A Tester verdict must exist on the PR, cover the head commit, and say Pass.

    A verdict that lives only in a transcript does not exist as far as this
    gate is concerned. That is the point: the PR is the durable record.
    """
    covering, stale = _verdicts(data, _is_tester_verdict)
    if not covering:
        if stale:
            return Result(
                "tester verdict", False, "the Tester verdict predates the head commit — re-test it"
            )
        return Result("tester verdict", False, "no Tester verdict posted to the PR")
    match = TESTER_VERDICT.search(covering[-1])
    latest = match.group(1).lower() if match else "unreadable"
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
