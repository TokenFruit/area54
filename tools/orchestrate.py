"""Run the published sequence, instead of hoping a human remembers to.

`team/TEAM.md` publishes the pipeline and `.claude/commands/` describe each
step, but nothing executes them: a human reads the prose and decides to comply.
In one day that produced six skipped steps — `/review` never run on two PRs, a
handoff announced and never sent, four PRs left in draft after CI went green.
Every one of those is mechanically visible in GitHub.

So this derives state rather than storing it. There is no state file, and that
is deliberate: every drift bug in this repo came from state living somewhere
that could disagree with reality. A spec on disk, its Status line, an ADR, a
branch, a PR's draft flag, its verdicts and its check conclusions are the truth,
and they are all readable on demand.

    python -m tools.orchestrate status --repo owner/name
    python -m tools.orchestrate next --repo owner/name
    python -m tools.orchestrate next --repo owner/name --run

`--run` dispatches exactly one action and stops. It may run an agent and it may
mark a PR ready for review. It never merges: the merge gate and the shell guard
own that step, and nothing here may go around them.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tools.agents import cli_invocation, load_agents
from tools.merge_gate import LEAD_APPROVE, LEAD_REJECT, NO_SPEC_WAIVER, TESTER_VERDICT

REPO_ROOT = Path(__file__).resolve().parent.parent

TF = re.compile(r"\bTF-(\d+)\b", re.IGNORECASE)
BRANCH_TF = re.compile(r"^(?:origin/)?tf-(\d+)-", re.IGNORECASE)
SPEC_STATUS = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z]+)", re.MULTILINE)

#: Which Builder owns a fix. The split between the two is a judgement about the
#: diff that this cannot make, so it names the backend and leaves the swap to
#: whoever reads the line — the same default `/build` uses when work collides.
OWNING_BUILDER = "builder-backend"


class OrchestratorError(Exception):
    """The state could not be read, or an action refuses to run. Never a no-op."""


@dataclass(frozen=True)
class Item:
    """One roadmap item, as derived from disk and GitHub. Nothing is stored."""

    tf: str
    spec_status: str | None = None
    #: The PR body states `No spec: <reason>`, the waiver the merge gate accepts.
    spec_waived: bool = False
    has_adr: bool = False
    branch: str | None = None
    pr: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """What the sequence says happens next for one item.

    ``kind`` is what would run it: ``agent`` dispatches a role, ``ready`` marks
    the PR ready for review, ``cpo`` is one of the two gates and is never
    dispatched, ``wait`` is something already in flight elsewhere.
    """

    stage: str
    blocked_on: str
    kind: str
    agent: str | None = None
    prompt: str | None = None


def _gh(args: list[str]) -> str:
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)  # noqa: S603
    except FileNotFoundError as exc:
        raise OrchestratorError("the gh CLI is not installed; state cannot be read.") from exc
    except subprocess.CalledProcessError as exc:
        raise OrchestratorError(f"gh {' '.join(args)} failed: {exc.stderr.strip()[:200]}") from exc
    return done.stdout


def _number(tf: str) -> str:
    """Normalise `TF-021`, `tf-21` and `21` to one key. Both forms are in use."""
    match = TF.search(tf) or re.search(r"(\d+)", tf)
    return str(int(match.group(1))) if match else tf


def fetch(repo: str, root: Path = REPO_ROOT) -> list[Item]:
    """Read every in-flight item's state from disk and from GitHub.

    Kept apart from `evaluate` so the decisions can be tested against fixture
    dicts without a live `gh`, exactly as the merge gate separates the two.
    """
    specs: dict[str, str | None] = {}
    for path in sorted((root / "docs" / "specs").glob("TF-*.md")):
        text = path.read_text(encoding="utf-8")
        match = SPEC_STATUS.search(text)
        specs[_number(path.stem)] = match.group(1) if match else None

    adrs = {
        key
        for path in (root / "docs" / "adr").glob("*.md")
        for key in {_number(m.group(0)) for m in TF.finditer(path.read_text(encoding="utf-8"))}
    }

    branches: dict[str, str] = {}
    listed = subprocess.run(  # noqa: S603
        ["git", "branch", "-a", "--format=%(refname:short)"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in listed.stdout.splitlines():
        if match := BRANCH_TF.match(line.strip()):
            branches.setdefault(_number(match.group(1)), line.strip())

    prs: dict[str, dict[str, object]] = {}
    fields = "number,url,title,body,isDraft,headRefName,statusCheckRollup,commits"
    for pr in json.loads(_gh(["pr", "list", "--repo", repo, "--state", "open", "--json", fields])):
        found = BRANCH_TF.match(str(pr.get("headRefName", ""))) or TF.search(
            f"{pr.get('title', '')} {pr.get('body', '')}"
        )
        if not found:
            continue
        pr["comments"] = fetch_comments(int(pr["number"]), repo)
        prs[_number(found.group(1))] = pr

    keys = sorted(set(specs) | set(branches) | set(prs), key=int)
    return [
        Item(
            tf=f"TF-{int(key):03d}",
            spec_status=specs.get(key),
            spec_waived=bool(NO_SPEC_WAIVER.search(str(prs.get(key, {}).get("body") or ""))),
            has_adr=key in adrs,
            branch=branches.get(key),
            pr=prs.get(key, {}),
        )
        for key in keys
    ]


def fetch_comments(pr: int, repo: str) -> list[dict[str, str]]:
    """Return every comment and review body on *pr*, with the time it landed.

    The timestamp is what makes a stalled handoff visible: a verdict requesting
    changes with no commit after it is a defect nobody picked up.
    """
    comments = json.loads(_gh(["api", f"repos/{repo}/issues/{pr}/comments"]))
    reviews = json.loads(_gh(["api", f"repos/{repo}/pulls/{pr}/reviews"]))
    return [
        {"body": str(c.get("body") or ""), "at": str(c.get("created_at") or "")} for c in comments
    ] + [
        {"body": str(r.get("body") or ""), "at": str(r.get("submitted_at") or "")} for r in reviews
    ]


def ci_state(pr: dict[str, object]) -> str:
    """One of `green`, `failing`, `pending`, `none`.

    No checks reported is `none`, never `green` — the same refusal the merge
    gate makes, for the same reason.
    """
    rollup = pr.get("statusCheckRollup")
    if not isinstance(rollup, list) or not rollup:
        return "none"
    states = [
        str(c.get("conclusion") or c.get("status") or c.get("state") or "").upper()
        for c in rollup
        if isinstance(c, dict)
    ]
    if any(s in {"", "PENDING", "IN_PROGRESS", "QUEUED", "WAITING"} for s in states):
        return "pending"
    if all(s in {"SUCCESS", "NEUTRAL", "SKIPPED"} for s in states):
        return "green"
    return "failing"


def _comments(pr: dict[str, object]) -> list[dict[str, str]]:
    raw = pr.get("comments", [])
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


#: What each role's verdict looks like, borrowed from the merge gate so the two
#: agree on what a verdict is. A verdict that lives in a transcript does not
#: exist — not to the next reader, not to the gate, and not here.
VERDICTS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Lead": (LEAD_APPROVE, LEAD_REJECT),
    "Tester": (TESTER_VERDICT,),
}


def latest_verdict(pr: dict[str, object], role: str) -> dict[str, str] | None:
    """The most recent verdict *role* posted to the PR, or None."""
    found = [c for c in _comments(pr) if any(p.search(c["body"]) for p in VERDICTS[role])]
    return found[-1] if found else None


def missing_verdicts(pr: dict[str, object]) -> list[str]:
    """The roles that have posted no verdict to the PR."""
    return [role for role in VERDICTS if latest_verdict(pr, role) is None]


def latest_commit(pr: dict[str, object]) -> str:
    """The most recent commit timestamp on the PR, as GitHub reports it.

    ISO-8601 in UTC from both endpoints, so ordering is a string comparison.
    """
    commits = pr.get("commits")
    if not isinstance(commits, list):
        return ""
    dates = [str(c.get("committedDate") or "") for c in commits if isinstance(c, dict)]
    return max(dates, default="")


def changes_requested(pr: dict[str, object]) -> bool:
    """Whether the latest Lead verdict asks for changes and nothing has moved."""
    verdict = latest_verdict(pr, "Lead")
    if verdict is None or LEAD_APPROVE.search(verdict["body"]):
        return False
    return latest_commit(pr) <= verdict["at"]


def stalls(item: Item) -> list[str]:
    """Name every stalled handoff on *item*. All three happened in one day."""
    pr = item.pr
    if not pr:
        return []
    found = []
    if changes_requested(pr):
        found.append("changes requested, and no commit since — the fix was never picked up")
    green = ci_state(pr) == "green"
    missing = missing_verdicts(pr)
    if green and not pr.get("isDraft") and missing:
        found.append(f"CI green and open for review, but no {' or '.join(missing)} verdict")
    if green and pr.get("isDraft"):
        found.append("CI green and still a draft — nobody marked it ready")
    return found


def next_action(item: Item) -> Action:
    """The dispatch table: in state X, on condition Y, the next action is Z.

    Ordered — the first clause that holds decides, so the earlier a clause sits
    the more it takes precedence. It follows `## How the work flows` and the
    seven command files.

    Where those two are ambiguous — the diagram draws the gates and Lead/Tester
    *before* "PR opened", while `/build` opens a draft PR as its last step and
    `/review` reviews an open one — this takes the commands' reading: the draft
    PR opens first, and the review runs against it.
    """
    pr, ci = item.pr, ci_state(item.pr)
    if item.spec_status is None and not item.spec_waived:
        return Action(
            "Needs spec",
            "no spec in docs/specs/",
            "agent",
            "product-owner",
            f"Groom {item.tf} into a buildable spec, following .claude/commands/groom.md.",
        )
    if item.spec_status and item.spec_status.lower() == "draft":
        return Action("Awaiting approval", "CPO gate 1 — the spec needs approval", "cpo")
    # An ADR is written *from* a spec, so a waived item is not owed one either.
    if item.spec_status and not item.has_adr:
        return Action(
            "Designing",
            "spec approved, no ADR",
            "agent",
            "architect",
            f"Write the ADR for {item.tf}, following .claude/commands/design.md.",
        )
    if not pr:
        return Action(
            "Building",
            "branch exists, no PR" if item.branch else "ADR written, no branch",
            "agent",
            OWNING_BUILDER,
            f"Build {item.tf} and open a draft PR, following .claude/commands/build.md.",
        )
    if ci == "failing":
        return Action(
            "Building",
            "CI is failing on this head",
            "agent",
            OWNING_BUILDER,
            f"CI is failing on the PR for {item.tf}. Fix the cause, not the test.",
        )
    if changes_requested(pr):
        return Action(
            "Defect loop",
            "latest Lead verdict requests changes, and no commit since",
            "agent",
            OWNING_BUILDER,
            f"Address the Lead's findings on the PR for {item.tf}, then hand it back to the "
            f"lead and the tester. Never edit the failing test.",
        )
    # "PRs open as draft, and are marked ready only when CI is green."
    if pr.get("isDraft") and ci == "green":
        return Action("In review", "CI green and still a draft", "ready")
    if missing := missing_verdicts(pr):
        return Action(
            "In review",
            f"no {' or '.join(missing)} verdict on the PR",
            "agent",
            # `/review` runs both in parallel; `--run` dispatches one at a time,
            # so the Lead goes first and the next run picks the Tester up.
            "lead" if "Lead" in missing else "tester",
            f"Review the PR for {item.tf}, following .claude/commands/review.md. Post your "
            f"verdict to the PR — a verdict in a transcript does not exist.",
        )
    if ci != "green":
        return Action("In review", f"CI is {ci}", "wait")
    return Action("Ready to ship", "CPO gate 2 — approve, then /ship", "cpo")


def in_flight(items: list[Item]) -> list[Item]:
    """Drop what is finished: shipped specs, and branches left behind by a merge.

    A local branch that outlived its merged PR carries a TF number and nothing
    else. Reporting it as work needing a spec is noise, and noise is how the
    published sequence stopped being read in the first place.
    """
    return [
        i
        for i in items
        if i.pr or (i.spec_status is not None and i.spec_status.lower() != "shipped")
    ]


def dispatch(action: Action, item: Item, repo: str) -> list[str]:
    """Return the argv that performs *action*, or refuse.

    Two kinds are dispatchable and no others. Nothing here may merge: the merge
    gate plus the shell guard own that step, and an orchestrator that could
    reach around them would undo the one gate that is code rather than
    judgement.
    """
    if action.kind == "ready":
        argv = ["gh", "pr", "ready", str(item.pr.get("number")), "--repo", repo]
    elif action.kind == "agent" and action.agent and action.prompt:
        agent = next((a for a in load_agents() if a.name == action.agent), None)
        if agent is None:
            raise OrchestratorError(f"no agent definition named '{action.agent}'.")
        argv = cli_invocation(agent, action.prompt)
    else:
        raise OrchestratorError(
            f"'{action.kind}' is not dispatchable: {action.blocked_on}. This one is the CPO's."
        )
    if any(arg == "merge" for arg in argv):
        raise OrchestratorError("refusing: nothing here may merge. Use the merge gate.")
    return argv


def print_status(items: list[Item]) -> None:
    print(f"{'TF':8} {'Stage':16} {'Blocked on'}")
    for item in items:
        action = next_action(item)
        print(f"{item.tf:8} {action.stage:16} {action.blocked_on}")
    stalled = [(i, s) for i in items for s in stalls(i)]
    if not stalled:
        return
    print(f"\nStalled ({len(stalled)}):")
    for item, reason in stalled:
        print(f"  {item.tf} #{item.pr.get('number')}: {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.orchestrate", description=__doc__)
    parser.add_argument("command", choices=("status", "next"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run", action="store_true", help="dispatch one action and stop")
    args = parser.parse_args(argv)

    try:
        items = in_flight(fetch(args.repo))
    except OrchestratorError as exc:
        print(f"::error::state could not be read: {exc}")
        print("Refusing. An unread pipeline is not an idle one.")
        return 1

    if not items:
        print("Nothing in flight.")
        return 0
    if args.command == "status":
        print_status(items)
        return 0

    for item in items:
        action = next_action(item)
        runner = "the CPO" if action.kind == "cpo" else action.agent or action.kind
        print(f"{item.tf}: {action.blocked_on} → {runner}")
        if not args.run or action.kind not in {"agent", "ready"}:
            continue
        try:
            command = dispatch(action, item, args.repo)
        except OrchestratorError as exc:
            print(f"::error::{item.tf} could not be dispatched: {exc}")
            return 1
        print(f"  running: {' '.join(command[:3])} …")
        return subprocess.run(command, check=False).returncode  # noqa: S603
    return 0


if __name__ == "__main__":
    sys.exit(main())
