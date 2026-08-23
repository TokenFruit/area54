"""Run the published sequence, instead of hoping a human remembers to.

`team/TEAM.md` publishes the pipeline and `.claude/commands/` describe each
step, but nothing executes them: a human reads the prose and decides to comply.
In one day that produced six skipped steps — `/review` never run on two PRs, a
handoff announced and never sent, four PRs left in draft after CI went green.

So this derives state rather than storing it. There is no state file: every drift
bug here came from state that could disagree with reality. The roadmap, a spec's
Status line, an ADR, a branch, a PR's flags, verdicts and checks are the truth.

    python -m tools.orchestrate {status,next} --repo owner/name [--run]

`--run` dispatches exactly one action and stops — an agent, or marking a PR
ready. It builds no other command, and `dispatch` refuses to run one. The merge
gate and `.claude/hooks/guard_bash.py` are what hold the merge itself: nothing
here can pass that guard, and nothing here is the reason it holds.
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
from tools.merge_gate import (
    LEAD_APPROVE,
    LEAD_COUNTS,
    LEAD_REJECT,
    NO_SPEC_WAIVER,
    TESTER_VERDICT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

TF = re.compile(r"\bTF-(\d+)\b", re.IGNORECASE)
BRANCH_TF = re.compile(r"^(?:origin/)?tf-(\d+)-", re.IGNORECASE)
SPEC_STATUS = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z]+)", re.MULTILINE)
#: The line the Architect's ADR template opens with (`.claude/agents/architect.md:40`).
#: An ADR is claimed by this line and nowhere else — the anchor `BRANCH_TF` is for a PR.
ADR_IMPLEMENTS = re.compile(r"^\*\*Implements:\*\*(.*)$", re.MULTILINE)

#: The roadmap section a dispatchable item sits in. An item the CPO has moved
#: out of it is reported and never started: that is what moving it out means.
ACTIVE_SECTION = "Now"

#: Which Builder owns a fix. The split is a judgement about the diff that this
#: cannot make, so it names the backend — the default `/build` uses — and leaves
#: the swap to whoever reads the line.
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
    #: The roadmap section this item sits under, or None if the roadmap has no
    #: line for it. `Done` outranks every other signal; only `Now` is dispatched.
    section: str | None = None
    #: The newest merged PR whose branch names this item, if there is one.
    merged_pr: int | None = None
    branch: str | None = None
    pr: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """What the sequence says happens next for one item.

    ``kind`` is what would run it: ``agent`` dispatches a role, ``ready`` marks
    the PR ready, ``cpo`` is a gate and is never dispatched, ``wait`` is elsewhere.
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


def owning_item(pr: dict[str, object]) -> str | None:
    """The item a PR belongs to, read from its branch name — `tf-021-*` — or None.

    Only the branch. A TF number in a title or body is a mention — #28 rescopes
    TF-021 and implements none of it — and reading one reported TF-021 as in
    review on somebody else's PR. No body fallback is safe, so there is none.
    """
    match = BRANCH_TF.match(str(pr.get("headRefName", "")))
    return _number(match.group(1)) if match else None


def roadmap_sections(root: Path = REPO_ROOT) -> dict[str, str]:
    """Every TF number the roadmap lists, and the section heading it sits under.

    All of the sections, not just `Done`: `Now` is what the team is working on,
    `Next` is committed but not started, `Later` is not committed. Only `Now` is
    dispatched — TF-020 sits in `Next` annotated "Paused at design,
    deliberately", and `next --run` sent an Architect at it.
    """
    path = root / "docs" / "roadmap.md"
    sections: dict[str, str] = {}
    section = ""
    for line in (path.read_text(encoding="utf-8") if path.exists() else "").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith(("- [ ]", "- [x]")) and (match := TF.search(line)):
            # The tick is what retires an item, so an unticked line under `Done`
            # is a line half-written rather than finished work: it stays active.
            ticked = line.startswith("- [x]")
            sections[_number(match.group(0))] = (
                section if ticked or section != "Done" else ACTIVE_SECTION
            )
    return sections


def adr_items(root: Path = REPO_ROOT) -> set[str]:
    """Every TF number an ADR states it implements, read from that line alone.

    A number in the prose is a mention — "this supersedes the approach proposed
    for TF-020" — and claiming by mention is what 0bd582a removed from PR
    ownership. It costs more here: an item wrongly credited with an ADR skips
    the Architect and is built without one, silently rather than with an error.
    """
    lines = (
        line
        for path in (root / "docs" / "adr").glob("*.md")
        for line in ADR_IMPLEMENTS.findall(path.read_text(encoding="utf-8"))
    )
    return {_number(match.group(0)) for line in lines for match in TF.finditer(line)}


def fetch(repo: str, root: Path = REPO_ROOT) -> list[Item]:
    """Read every item's state from disk and from GitHub.

    Kept apart from the decisions so those can be tested against fixture dicts
    without a live `gh`, exactly as the merge gate separates the two.
    """
    specs: dict[str, str | None] = {}
    for path in sorted((root / "docs" / "specs").glob("TF-*.md")):
        text = path.read_text(encoding="utf-8")
        match = SPEC_STATUS.search(text)
        specs[_number(path.stem)] = match.group(1) if match else None

    adrs = adr_items(root)

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
    loose: list[dict[str, object]] = []
    fields = (
        "number,url,title,body,isDraft,autoMergeRequest,"
        "headRefName,headRefOid,statusCheckRollup,commits"
    )
    listed_prs = _gh(["pr", "list", "--repo", repo, "--state", "open", "--json", fields])
    for pr in sorted(json.loads(listed_prs), key=lambda p: int(p["number"]), reverse=True):
        pr["comments"] = fetch_comments(int(pr["number"]), repo)
        # The highest number wins the item: it is the newest PR on it. The older
        # one is not dropped — last-write-wins over `gh pr list` order lost a
        # whole PR, and any stall on it, without printing a line. It gets a row
        # of its own, exactly as a PR that names no item does.
        if (key := owning_item(pr)) and key not in prs:
            prs[key] = pr
        else:
            loose.append(pr)

    # A merged PR on the item's branch is the code already being in `main`, and
    # the roadmap always lags a merge: TF-019 merged in #23 and was ticked into
    # `Done` hours later. `--state open` could not see it, so for that whole
    # window the item read "branch exists, no PR" and `--run` would have sent a
    # Builder at finished work. Highest number wins, as with the open ones.
    merged = ["pr", "list", "--repo", repo, "--state", "merged", "--json", "number,headRefName"]
    shipped: dict[str, int] = {}
    for pr in sorted(json.loads(_gh(merged)), key=lambda p: int(p["number"])):
        if key := owning_item(pr):
            shipped[key] = int(pr["number"])

    # An item in `Now` is on the board before anything else exists for it — that
    # is how `Needs spec` is reached before the code rather than after it, and
    # TF-003 sat in `Now` invisible to `status` and to `next`.
    sections = roadmap_sections(root)
    active = {key for key, section in sections.items() if section == ACTIVE_SECTION}
    keys = sorted(set(specs) | set(branches) | set(prs) | active, key=int)
    return [
        Item(
            tf=f"TF-{int(key):03d}",
            spec_status=specs.get(key),
            spec_waived=bool(NO_SPEC_WAIVER.search(str(prs.get(key, {}).get("body") or ""))),
            has_adr=key in adrs,
            section=sections.get(key),
            merged_pr=shipped.get(key),
            branch=branches.get(key),
            pr=prs.get(key, {}),
        )
        for key in keys
    ] + [
        # A PR on no roadmap item is owed no spec — there is no line to groom —
        # but it stays on the board, so a stall on it is named against no item
        # instead of the wrong one.
        Item(tf=str(pr.get("headRefName")), spec_waived=True, pr=pr)
        for pr in loose
    ]


def fetch_comments(pr: int, repo: str) -> list[dict[str, str]]:
    """Every comment and review body on *pr*, with the time it landed.

    The timestamp is what makes a stalled handoff visible: changes requested
    with no commit after them is a defect nobody picked up.

    Paginated, because the page-one default is 30 and this fails *open*: a
    verdict that is not fetched is a verdict missing, and a missing verdict
    dispatches the role that already posted it. It posts number 32, which is not
    fetched either, and `--run` re-dispatches for as long as anyone runs it.
    """
    comments = json.loads(_gh(["api", "--paginate", f"repos/{repo}/issues/{pr}/comments"]))
    reviews = json.loads(_gh(["api", "--paginate", f"repos/{repo}/pulls/{pr}/reviews"]))
    return [
        {"body": str(c.get("body") or ""), "at": str(c.get("created_at") or "")} for c in comments
    ] + [
        {"body": str(r.get("body") or ""), "at": str(r.get("submitted_at") or "")} for r in reviews
    ]


def ci_state(pr: dict[str, object]) -> str:
    """One of `green`, `failing`, `pending`, `none`.

    Green is exactly the merge gate's `{SUCCESS, NEUTRAL}`, and the gate is the
    authority: anything it refuses must not be reported ready here. No checks
    reported is `none`, and a `SKIPPED` required check — a path filter, a
    conditional job — is not green either. Calling it green spent a Lead and a
    Tester round on a PR the gate then refused.
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
    if all(s in {"SUCCESS", "NEUTRAL"} for s in states):
        return "green"
    return "failing"


#: What each role's verdict looks like, borrowed from the merge gate so the two
#: agree. A verdict that lives in a transcript does not exist — not to the next
#: reader, not to the gate, not here.
VERDICTS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Lead": (LEAD_APPROVE, LEAD_REJECT),
    "Tester": (TESTER_VERDICT,),
}


#: Sorts after any ISO-8601 timestamp, so a head that cannot be dated makes
#: every verdict stale. The gate refuses such a PR outright; refusing here means
#: sending it back for a review that can be dated.
UNDATEABLE = "9999"


def latest_commit(pr: dict[str, object]) -> str:
    """When the head commit was made: ISO-8601 UTC, so ordering is a string compare.

    Matched by SHA where the PR reports one, as `tools/merge_gate.py` dates the
    head; the newest `committedDate` otherwise, which is that same commit on any
    history the gate would accept.
    """
    raw = pr.get("commits")
    commits = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    head = str(pr.get("headRefOid") or "")
    matched = [c for c in commits if str(c.get("oid") or "") == head] if head else []
    dated = (str(c.get("committedDate") or "") for c in (matched or commits))
    return max(dated, default=UNDATEABLE)


def latest_verdict(pr: dict[str, object], role: str) -> dict[str, str] | None:
    """The most recent verdict *role* posted about the current head, or None.

    Ordered by `at` rather than by list order: `fetch_comments` returns every
    issue comment and then every review, so the two interleave in time and the
    last of the list is not the latest.

    A verdict counts only if posted strictly after the head commit was made; an
    equal timestamp is stale, since GitHub stamps to the second and a verdict
    sharing the commit's second may have been written just before it. That is
    `tools/merge_gate.py`'s rule, refusing the same sequence: approve, push,
    wait for green, merge what nobody read.
    """
    raw = pr.get("comments", [])
    head = latest_commit(pr)
    posted = sorted(
        (
            {"body": str(c.get("body") or ""), "at": str(c.get("at") or "")}
            for c in (raw if isinstance(raw, list) else [])
            if isinstance(c, dict)
        ),
        key=lambda c: c["at"],
    )
    fresh = [
        c for c in posted if c["at"] > head and any(p.search(c["body"]) for p in VERDICTS[role])
    ]
    return fresh[-1] if fresh else None


def missing_verdicts(pr: dict[str, object]) -> list[str]:
    """The roles that have posted no verdict covering the PR's head commit."""
    return [role for role in VERDICTS if latest_verdict(pr, role) is None]


def rejecting_verdict(pr: dict[str, object]) -> str | None:
    """The role whose current verdict refuses this head, or None.

    What counts as a refusal is the merge gate's answer, not a looser one: an
    approval reporting blockers or majors is refused there by `LEAD_COUNTS`, and
    a Tester `Fail` by `check_tester_verdict`. Reading only the word `Approve`
    reported this PR "Ready to ship" on a live board while the Lead's two
    blockers and the Tester's Fail stood — the Lead's review quotes the string
    `**Verdict: Approve.**` inside a finding, and a quote read as a verdict.

    A verdict the head commit postdates is not returned at all, so the defect
    loop still leaves on a commit.
    """
    lead = latest_verdict(pr, "Lead")
    if lead is not None and (
        not LEAD_APPROVE.search(lead["body"])
        or any(int(m.group(1) or m.group(2) or 0) > 0 for m in LEAD_COUNTS.finditer(lead["body"]))
    ):
        return "Lead"
    tester = latest_verdict(pr, "Tester")
    if tester is not None and (match := TESTER_VERDICT.search(tester["body"])):
        return "Tester" if match.group(1).lower() == "fail" else None
    return None


def stalls(item: Item) -> list[str]:
    """Name every stalled handoff on *item*. All three happened in one day."""
    pr = item.pr
    if not pr:
        return []
    found = []
    if role := rejecting_verdict(pr):
        found.append(f"the {role} refused this head, and no commit since — nobody picked it up")
    green = ci_state(pr) == "green"
    missing = missing_verdicts(pr)
    if green and not pr.get("isDraft") and missing:
        found.append(f"CI green and open for review, but no {' or '.join(missing)} verdict")
    if green and pr.get("isDraft"):
        found.append("CI green and still a draft — nobody marked it ready")
    return found


def next_action(item: Item) -> Action:
    """The dispatch table: in state X, on condition Y, the next action is Z.

    Ordered — the first clause that holds decides. It follows `## How the work
    flows` and the seven command files; where those are ambiguous it takes the
    commands' reading: the draft PR opens first, and `/review` runs against it.
    """
    pr, ci = item.pr, ci_state(item.pr)
    if item.section not in (None, ACTIVE_SECTION):
        return Action(
            "Not started",
            f"the CPO has this in `{item.section}`, not `{ACTIVE_SECTION}`",
            "wait",
        )
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
    if not pr and item.merged_pr:
        # Reported, never dispatched: only the CPO ticks the roadmap, and the
        # one wrong answer for code already in `main` is to write it again.
        return Action(
            "Merged",
            f"#{item.merged_pr} is merged; the roadmap's `Done` section has not caught up",
            "cpo",
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
    if role := rejecting_verdict(pr):
        return Action(
            "Defect loop",
            f"the latest {role} verdict refuses this head, and no commit since",
            "agent",
            OWNING_BUILDER,
            f"Address the {role}'s findings on the PR for {item.tf}. Never edit the failing test.",
        )
    # "PRs open as draft, and are marked ready only when CI is green."
    if pr.get("isDraft") and ci == "green":
        return Action("In review", "CI green and still a draft", "ready")
    if missing := missing_verdicts(pr):
        return Action(
            "In review",
            f"no {' or '.join(missing)} verdict on the PR",
            "agent",
            # `/review` runs both in parallel; `--run` dispatches one at a time.
            "lead" if "Lead" in missing else "tester",
            f"Review the PR for {item.tf}, following .claude/commands/review.md. Post the "
            f"verdict to the PR — one in a transcript does not exist.",
        )
    if ci != "green":
        return Action("In review", f"CI is {ci}", "wait")
    return Action("Ready to ship", "CPO gate 2 — approve, then /ship", "cpo")


def in_flight(items: list[Item]) -> list[Item]:
    """Drop what is finished. The roadmap decides first; everything else after.

    A `- [x]` line under `Done` is the CPO saying the work shipped, and it
    outranks a branch, a PR and a spec alike — TF-019 shipped in #23 and its two
    undeleted branches went on reporting it as Building, which under `--run`
    dispatches a Builder at finished work. A branch is evidence a branch was
    never deleted, nothing more.
    """
    unfinished = [i for i in items if i.section != "Done"]
    return [
        i
        for i in unfinished
        # A line in `Now` with nothing else to show for it is the one state that
        # needs the Product Owner, so it is work; a spec-less branch is residue.
        if i.pr
        or i.section == ACTIVE_SECTION
        or (i.spec_status or "").lower() not in {"", "shipped"}
    ]


def dispatch(action: Action, item: Item, repo: str) -> list[str]:
    """Return the argv that performs *action*, or refuse.

    Two kinds are dispatchable and no others, and what may run is stated as a
    shape rather than as a word to scan for. Scanning found `merge` as a whole
    argv element and nothing else, so `gh pr MERGE`, `gh pr merge-queue add`,
    `gh pr --merge` and `sh -c "gh pr merge 29"` all passed it.

    What actually stops a merge is `.claude/hooks/guard_bash.py`, which refuses
    `gh pr merge` without a live authorisation naming that PR at that head. This
    is the narrower claim it can keep: a clause added later that builds some
    other `gh` call does not get to run unread.
    """
    if action.kind == "ready":
        # `gh pr ready` is not inert on a PR with auto-merge enabled: GitHub
        # merges it the moment it is non-draft and its checks pass, and no
        # command is issued, so neither the gate nor the shell guard is
        # consulted. This clause only fires when CI is already green, so that
        # is the same second. Enabling auto-merge is the CPO's to undo.
        if item.pr.get("autoMergeRequest"):
            raise OrchestratorError(
                f"refusing: auto-merge is enabled on #{item.pr.get('number')}, so marking it "
                "ready would merge it without the gate. Turn auto-merge off, or run /ship."
            )
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
    if argv[:3] != ["gh", "pr", "ready"] and argv[:1] != ["claude"]:
        raise OrchestratorError(
            f"refusing to run {' '.join(argv[:3])}: only `gh pr ready` and a `claude` agent "
            "invocation may be dispatched. The merge belongs to the gate."
        )
    return argv


def print_status(items: list[Item]) -> None:
    width = max((len(i.tf) for i in items), default=8)
    print(f"{'TF':{width}} {'Stage':16} {'Blocked on'}")
    for item in items:
        action = next_action(item)
        print(f"{item.tf:{width}} {action.stage:16} {action.blocked_on}")
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
        runner = {"cpo": "the CPO", "wait": "nobody"}.get(action.kind) or action.agent or "nobody"
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
