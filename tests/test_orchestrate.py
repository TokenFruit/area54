"""Tests for the orchestrator.

The published sequence was executed by a human deciding to comply with it, and
in one day six steps were skipped. These pin the dispatch table — every state
in it — and the three stalls that actually happened. Deciding is kept apart
from fetching, so none of this touches a live `gh`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import orchestrate
from tools.merge_gate import check_ci_green
from tools.orchestrate import (
    UNDATEABLE,
    Action,
    Item,
    OrchestratorError,
    adr_items,
    ci_state,
    dispatch,
    fetch,
    fetch_comments,
    in_flight,
    latest_commit,
    latest_verdict,
    missing_verdicts,
    next_action,
    owning_item,
    rejecting_verdict,
    roadmap_sections,
    stalls,
)

ROADMAP = """# Roadmap

## Now

- [ ] TF-021 — The orchestrator. Nothing checks that a handoff happened
- [ ] TF-003 — Package the team as a Claude Code plugin

## Next

- [ ] TF-020 — Learn from the transcripts. **Paused at design**, deliberately

## Later

- [ ] Per-repo team profiles — not every product needs all seven roles

## Done

- [x] **TF-019** — The escalation contract: two closed lists in TEAM.md — 2026-08-23
- [x] **TF-009** — First real feature end to end: TF-001 shipped through review

---

### How an item moves
"""

GREEN = [{"name": "Typecheck / Lint / Test", "conclusion": "SUCCESS"}]
LEAD_OK = "## Lead review\n\n**Verdict: Approve.** 0 blockers, 0 majors."
LEAD_NO = "## Lead review\n\n**Changes requested.** 1 blocker."
TESTER_OK = "## Tester report\n\n**Tester verdict: Pass** — 9/9 criteria covered."


def pr(**overrides: object) -> dict[str, object]:
    """A PR mid-review: open, green, both verdicts in, ready for the CPO."""
    data: dict[str, object] = {
        "number": 42,
        "isDraft": False,
        "statusCheckRollup": list(GREEN),
        "commits": [{"committedDate": "2026-08-24T09:00:00Z"}],
        "comments": [
            {"body": LEAD_OK, "at": "2026-08-24T10:00:00Z"},
            {"body": TESTER_OK, "at": "2026-08-24T10:05:00Z"},
        ],
    }
    data.update(overrides)
    return data


def item(**overrides: object) -> Item:
    """An item whose every earlier stage is satisfied, so a test breaks one."""
    base: dict[str, object] = {
        "tf": "TF-021",
        "spec_status": "Approved",
        "has_adr": True,
        "branch": "tf-021-orchestrator",
        "pr": pr(),
    }
    base.update(overrides)
    return Item(**base)  # type: ignore[arg-type]


# --- the dispatch table, state by state -------------------------------------


def test_no_spec_goes_to_the_product_owner() -> None:
    action = next_action(item(spec_status=None))
    assert action.stage == "Needs spec"
    assert action.agent == "product-owner"


def test_a_cpo_spec_waiver_skips_both_the_spec_and_the_adr() -> None:
    """`No spec: <reason>` in the PR body, the waiver the merge gate accepts."""
    waived = item(spec_status=None, spec_waived=True, has_adr=False)
    assert next_action(waived).stage == "Ready to ship"


def test_a_draft_spec_waits_for_gate_one_and_dispatches_nobody() -> None:
    action = next_action(item(spec_status="Draft"))
    assert action.stage == "Awaiting approval"
    assert action.kind == "cpo"


def test_an_approved_spec_with_no_adr_goes_to_the_architect() -> None:
    action = next_action(item(has_adr=False))
    assert action.agent == "architect"
    assert action.blocked_on == "spec approved, no ADR"


def test_an_adr_with_no_branch_goes_to_a_builder() -> None:
    action = next_action(item(branch=None, pr={}))
    assert action.agent == "builder-backend"
    assert action.blocked_on == "ADR written, no branch"


def test_a_branch_with_no_pr_is_still_the_builders() -> None:
    action = next_action(item(pr={}))
    assert action.agent == "builder-backend"
    assert action.blocked_on == "branch exists, no PR"


def test_failing_ci_goes_back_to_the_builder() -> None:
    action = next_action(item(pr=pr(statusCheckRollup=[{"conclusion": "FAILURE"}])))
    assert action.agent == "builder-backend"
    assert "CI is failing" in action.blocked_on


def test_changes_requested_with_no_commit_since_goes_to_the_builder() -> None:
    stale = pr(comments=[{"body": LEAD_NO, "at": "2026-08-24T10:00:00Z"}])
    action = next_action(item(pr=stale))
    assert action.stage == "Defect loop"
    assert action.agent == "builder-backend"


def test_a_commit_after_the_verdict_moves_the_loop_on() -> None:
    fixed = pr(
        comments=[{"body": LEAD_NO, "at": "2026-08-24T10:00:00Z"}],
        commits=[{"committedDate": "2026-08-24T11:00:00Z"}],
    )
    assert rejecting_verdict(fixed) is None
    assert next_action(item(pr=fixed)).stage == "In review"


def test_a_verdict_the_head_commit_postdates_is_not_a_verdict() -> None:
    """The other direction of the same rule: approve, push, go green, ship unread."""
    unreviewed = pr(commits=[{"committedDate": "2026-08-24T11:00:00Z"}])
    assert missing_verdicts(unreviewed) == ["Lead", "Tester"]
    assert next_action(item(pr=unreviewed)).agent == "lead"
    assert stalls(item(pr=unreviewed)) == [
        "CI green and open for review, but no Lead or Tester verdict"
    ]


def test_a_verdict_in_the_commit_s_own_second_is_stale() -> None:
    """GitHub stamps to the second, and ambiguous is never a pass. The gate's rule."""
    same = pr(commits=[{"committedDate": "2026-08-24T10:05:00Z"}])
    assert missing_verdicts(same) == ["Lead", "Tester"]


def test_the_head_commit_is_the_one_the_sha_names() -> None:
    """`gh` lists the PR's commits; the gate dates the head by SHA, so this does too."""
    rebased = pr(
        headRefOid="cafe1234",
        commits=[
            {"oid": "cafe1234", "committedDate": "2026-08-24T09:00:00Z"},
            {"oid": "beef5678", "committedDate": "2026-08-24T12:00:00Z"},
        ],
    )
    assert latest_commit(rebased) == "2026-08-24T09:00:00Z"
    assert missing_verdicts(rebased) == []


def test_a_pr_whose_head_cannot_be_dated_has_no_current_verdict() -> None:
    """Undateable is not fresh. The gate refuses; here the PR goes back for review."""
    assert latest_commit(pr(commits=[])) == UNDATEABLE
    assert missing_verdicts(pr(commits=[])) == ["Lead", "Tester"]


def test_the_latest_verdict_is_the_latest_by_time_not_by_list_order() -> None:
    """Issue comments are fetched before reviews, so list order is not time order."""
    reordered = pr(
        comments=[
            {"body": LEAD_OK, "at": "2026-08-24T12:00:00Z"},
            {"body": LEAD_NO, "at": "2026-08-24T09:30:00Z"},
        ]
    )
    assert rejecting_verdict(reordered) is None
    verdict = latest_verdict(reordered, "Lead")
    assert verdict is not None and verdict["at"] == "2026-08-24T12:00:00Z"


def test_an_approval_that_predates_the_latest_rejection_does_not_hide_it() -> None:
    later_rejection = pr(
        comments=[
            {"body": LEAD_NO, "at": "2026-08-24T12:00:00Z"},
            {"body": LEAD_OK, "at": "2026-08-24T09:30:00Z"},
        ]
    )
    assert rejecting_verdict(later_rejection) == "Lead"
    assert next_action(item(pr=later_rejection)).stage == "Defect loop"


def test_an_approval_reporting_blockers_is_not_an_approval() -> None:
    """The live board's own failure: a quoted `Verdict: Approve` read as one.

    The Lead's review of this PR quotes the string inside a finding and closes
    `**Verdict: Changes requested** — 2 blockers`. The merge gate counts the
    blockers and refuses; reading the word alone reported "Ready to ship".
    """
    quoted = "The Lead posting `**Verdict: Approve.**` at 12:00 …\n\n2 blockers, 4 majors."
    refused = pr(comments=[{"body": quoted, "at": "2026-08-24T10:00:00Z"}])
    assert rejecting_verdict(refused) == "Lead"
    assert next_action(item(pr=refused)).stage == "Defect loop"


def test_a_tester_fail_is_a_refusal_not_a_verdict_in_hand() -> None:
    failed = pr(
        comments=[
            {"body": LEAD_OK, "at": "2026-08-24T10:00:00Z"},
            {"body": "**Tester verdict: Fail** — 3 defects.", "at": "2026-08-24T10:05:00Z"},
        ]
    )
    assert rejecting_verdict(failed) == "Tester"
    action = next_action(item(pr=failed))
    assert action.stage == "Defect loop"
    assert action.prompt is not None and "Tester's findings" in action.prompt


def test_a_lead_approval_with_no_counts_still_approves() -> None:
    """The other direction: `0 blockers, 0 majors` is what the gate lets through."""
    assert rejecting_verdict(pr()) is None
    assert next_action(item()).stage == "Ready to ship"


def test_a_merged_pr_is_not_work_for_a_builder() -> None:
    """TF-019 merged in #23 and was ticked into `Done` hours later.

    For that window the item read "branch exists, no PR" and `--run` would have
    dispatched `builder-backend` to build what was already in `main`.
    """
    lagging = item(merged_pr=23, branch="tf-019-escalation-build", pr={})
    action = next_action(lagging)
    assert action.stage == "Merged"
    assert action.kind == "cpo"
    assert "#23" in action.blocked_on
    with pytest.raises(OrchestratorError, match="not dispatchable"):
        dispatch(action, lagging, "TokenFruit/area54")


def test_an_open_pr_outranks_an_older_merged_one() -> None:
    """A second round on an item is in review, not finished."""
    reopened = item(merged_pr=23, pr=pr(comments=[]))
    assert next_action(reopened).agent == "lead"


def test_a_merged_pr_does_not_skip_a_stage_the_item_has_not_reached() -> None:
    """`tf-020-groom` merged the spec, not the feature. The clause is the Builder's."""
    groomed = item(merged_pr=25, has_adr=False, pr={})
    assert next_action(groomed).agent == "architect"


def test_a_green_draft_is_marked_ready() -> None:
    action = next_action(item(pr=pr(isDraft=True)))
    assert action.kind == "ready"


def test_a_pr_with_no_verdicts_goes_to_the_lead() -> None:
    action = next_action(item(pr=pr(comments=[])))
    assert action.agent == "lead"
    assert action.blocked_on == "no Lead or Tester verdict on the PR"


def test_a_missing_tester_verdict_alone_goes_to_the_tester() -> None:
    only_lead = pr(comments=[{"body": LEAD_OK, "at": "2026-08-24T10:00:00Z"}])
    assert next_action(item(pr=only_lead)).agent == "tester"


def test_pending_ci_is_waited_on_rather_than_dispatched() -> None:
    action = next_action(item(pr=pr(statusCheckRollup=[{"status": "IN_PROGRESS"}])))
    assert action.kind == "wait"


def test_everything_satisfied_reaches_gate_two() -> None:
    action = next_action(item())
    assert action.stage == "Ready to ship"
    assert action.kind == "cpo"


# --- CI conclusions ---------------------------------------------------------


@pytest.mark.parametrize(
    ("rollup", "expected"),
    [
        (GREEN, "green"),
        ([{"conclusion": "FAILURE"}], "failing"),
        ([{"conclusion": "SUCCESS"}, {"status": "QUEUED"}], "pending"),
        ([], "none"),
        (None, "none"),
    ],
)
def test_ci_states(rollup: object, expected: str) -> None:
    assert ci_state({"statusCheckRollup": rollup}) == expected


@pytest.mark.parametrize(
    "conclusion",
    ["SUCCESS", "NEUTRAL", "SKIPPED", "CANCELLED", "TIMED_OUT", "FAILURE", "QUEUED", ""],
)
def test_green_here_is_green_at_the_merge_gate(conclusion: str) -> None:
    """Both directions of one property: the gate is the authority on what green is.

    `SKIPPED` was green here and refused there, so a skipped required check was
    marked ready, reviewed twice, and reported ready to ship before the gate saw it.
    """
    data = {"statusCheckRollup": [{"name": "Typecheck / Lint / Test", "conclusion": conclusion}]}
    assert (ci_state(data) == "green") is check_ci_green(data).passed


def test_no_checks_reported_is_not_green() -> None:
    """The merge gate's refusal, for the same reason: absence is not a pass."""
    assert next_action(item(pr=pr(statusCheckRollup=[]))).kind == "wait"


# --- stalls: all three happened in one day ----------------------------------


def test_a_green_pr_still_in_draft_is_named_as_stalled() -> None:
    assert stalls(item(pr=pr(isDraft=True))) == [
        "CI green and still a draft — nobody marked it ready"
    ]


def test_a_green_open_pr_with_no_verdicts_is_named_as_stalled() -> None:
    found = stalls(item(pr=pr(comments=[])))
    assert found == ["CI green and open for review, but no Lead or Tester verdict"]


def test_an_unanswered_changes_requested_verdict_is_named_as_stalled() -> None:
    stale = pr(comments=[{"body": LEAD_NO, "at": "2026-08-24T10:00:00Z"}])
    assert "no commit since" in stalls(item(pr=stale))[0]


def test_a_healthy_pr_has_no_stalls() -> None:
    assert stalls(item()) == []


def test_an_item_with_no_pr_has_no_stalls() -> None:
    assert stalls(item(pr={})) == []


# --- dispatch ---------------------------------------------------------------


def test_dispatching_an_agent_uses_the_one_invocation_path() -> None:
    argv = dispatch(next_action(item(has_adr=False)), item(), "TokenFruit/area54")
    assert argv[0] == "claude"
    assert "--append-system-prompt" in argv
    assert "claude-opus-5" in argv


def test_marking_ready_names_the_pr_and_the_repo() -> None:
    argv = dispatch(Action("In review", "draft", "ready"), item(), "TokenFruit/area54")
    assert argv == ["gh", "pr", "ready", "42", "--repo", "TokenFruit/area54"]


def test_marking_ready_refuses_when_auto_merge_would_merge_it() -> None:
    """`gh pr ready` is not inert: GitHub merges a green PR with auto-merge set.

    No command is issued for that merge, so neither the gate nor the shell guard
    sees it, and this clause fires only when CI is already green.
    """
    armed = item(pr=pr(isDraft=True, autoMergeRequest={"enabledAt": "2026-08-24T09:00:00Z"}))
    action = next_action(armed)
    assert action.kind == "ready"
    with pytest.raises(OrchestratorError, match="auto-merge is enabled"):
        dispatch(action, armed, "TokenFruit/area54")


def test_marking_ready_goes_ahead_when_auto_merge_is_not_set() -> None:
    draft = item(pr=pr(isDraft=True, autoMergeRequest=None))
    argv = dispatch(next_action(draft), draft, "TokenFruit/area54")
    assert argv == ["gh", "pr", "ready", "42", "--repo", "TokenFruit/area54"]


def test_a_cpo_gate_refuses_to_be_dispatched() -> None:
    with pytest.raises(OrchestratorError, match="not dispatchable"):
        dispatch(next_action(item()), item(), "TokenFruit/area54")


def test_waiting_on_ci_refuses_to_be_dispatched() -> None:
    with pytest.raises(OrchestratorError, match="not dispatchable"):
        dispatch(Action("In review", "CI is pending", "wait"), item(), "TokenFruit/area54")


def test_an_unknown_agent_refuses_rather_than_guessing() -> None:
    action = Action("Building", "x", "agent", "builder-sideways", "do the thing")
    with pytest.raises(OrchestratorError, match="no agent definition"):
        dispatch(action, item(), "TokenFruit/area54")


def test_nothing_in_the_table_produces_a_merge() -> None:
    """The table's own output, which is the passing direction of the guard below."""
    for state in (item(spec_status=None), item(has_adr=False), item(pr=pr(isDraft=True))):
        argv = dispatch(next_action(state), state, "TokenFruit/area54")
        assert argv[:3] == ["gh", "pr", "ready"] or argv[:1] == ["claude"]


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "pr", "merge", "29", "--repo", "TokenFruit/area54"],
        ["gh", "pr", "MERGE", "29"],
        ["gh", "pr", "merge-queue", "add", "29"],
        ["gh", "pr", "--merge", "29"],
        ["sh", "-c", "gh pr merge 29"],
        ["gh", "pr", "close", "29"],
    ],
)
def test_the_guard_refuses_anything_that_is_not_one_of_the_two_shapes(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """The rejecting direction, which nothing exercised: the guard could be deleted.

    Only the first of these was refused before — the check was exact-token and
    case-sensitive, so uppercase, a subcommand prefix, a flag and a shell all
    walked through a guard the docstrings credited with stopping merges.
    """
    monkeypatch.setattr(orchestrate, "cli_invocation", lambda agent, prompt: argv)
    action = next_action(item(has_adr=False))
    with pytest.raises(OrchestratorError, match="only `gh pr ready`"):
        dispatch(action, item(), "TokenFruit/area54")


def test_the_guard_lets_an_agent_invocation_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """The passing direction, so the guard cannot be tightened into refusing everything."""
    monkeypatch.setattr(orchestrate, "cli_invocation", lambda agent, prompt: ["claude", "-p", "x"])
    argv = dispatch(next_action(item(has_adr=False)), item(), "TokenFruit/area54")
    assert argv == ["claude", "-p", "x"]


# --- which PR belongs to which item -----------------------------------------


def test_a_pr_belongs_to_the_item_its_branch_names() -> None:
    assert owning_item({"headRefName": "tf-021-orchestrator", "body": ""}) == "21"


def test_a_body_mentioning_an_item_does_not_own_it() -> None:
    """#28 rescopes TF-021 on a chore branch and implements none of it."""
    rescope: dict[str, object] = {
        "headRefName": "chore/roadmap-orchestrator",
        "title": "Put the orchestrator first",
        "body": "Promotes TF-021 to Now and pauses TF-020.",
    }
    assert owning_item(rescope) is None


def test_a_pr_on_no_item_is_reviewed_rather_than_groomed() -> None:
    """It is owed no spec: there is no roadmap line for a Product Owner to groom."""
    chore = item(
        tf="chore/roadmap-orchestrator",
        spec_status=None,
        spec_waived=True,
        has_adr=False,
        branch=None,
        pr=pr(comments=[]),
    )
    assert next_action(chore).stage == "In review"
    assert next_action(chore).agent == "lead"


def test_a_stall_on_a_pr_that_owns_no_item_is_still_named() -> None:
    """The true positive. Attributed to no item, never dropped."""
    chore = item(
        tf="chore/roadmap-orchestrator",
        spec_status=None,
        spec_waived=True,
        has_adr=False,
        branch=None,
        pr=pr(comments=[]),
    )
    assert in_flight([chore]) == [chore]
    assert stalls(chore) == ["CI green and open for review, but no Lead or Tester verdict"]


# --- fetch: the half that reads the world ------------------------------------


def roadmap(tmp_path: Path, text: str = ROADMAP) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "roadmap.md").write_text(text, encoding="utf-8")


def fetched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    open_prs: list[dict[str, object]] | None = None,
    merged_prs: list[dict[str, object]] | None = None,
    branches: str = "",
) -> list[Item]:
    """`fetch` over a stubbed `gh` and `git`. No process is started."""

    def gh(args: list[str]) -> str:
        if args[:2] == ["pr", "list"]:
            state = args[args.index("--state") + 1]
            return json.dumps((open_prs if state == "open" else merged_prs) or [])
        return "[]"

    def git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout=branches, stderr="")

    monkeypatch.setattr(orchestrate, "_gh", gh)
    monkeypatch.setattr(orchestrate.subprocess, "run", git)
    return fetch("TokenFruit/area54", tmp_path)


def test_a_second_pr_on_one_item_keeps_a_row_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Last-write-wins dropped one of them, and every stall on it with it."""
    items = fetched(
        monkeypatch,
        tmp_path,
        [
            {"number": 29, "headRefName": "tf-021-orchestrator", "body": ""},
            {"number": 31, "headRefName": "tf-021-deploy-the-gate", "body": ""},
        ],
    )
    owned = {i.tf: i.pr.get("number") for i in items}
    assert owned == {"TF-021": 31, "tf-021-orchestrator": 29}


def test_an_item_in_now_is_on_the_board_before_anything_exists_for_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TF-003 sat in `Now` with no spec, branch or PR, and was on no board at all."""
    roadmap(tmp_path)
    board = {i.tf: next_action(i) for i in in_flight(fetched(monkeypatch, tmp_path))}
    assert board["TF-003"].agent == "product-owner"
    assert board["TF-003"].stage == "Needs spec"


def test_next_and_later_are_not_seeded_onto_the_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Next` is committed, `Later` is not, and neither is work the team has picked up."""
    roadmap(tmp_path)
    assert [i.tf for i in fetched(monkeypatch, tmp_path)] == ["TF-003", "TF-021"]


def test_work_already_open_in_next_is_reported_but_never_dispatched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TF-020 is paused at design, and `next --run` sent an Architect at it."""
    roadmap(tmp_path)
    paused = fetched(
        monkeypatch, tmp_path, [{"number": 26, "headRefName": "tf-020-design", "body": ""}]
    )
    tf020 = next(i for i in paused if i.tf == "TF-020")
    assert tf020.section == "Next"
    action = next_action(tf020)
    assert action.stage == "Not started"
    assert action.kind == "wait"
    assert action.agent is None


def test_a_paused_item_still_has_its_stalls_named() -> None:
    """The filter must not lose the true positive it exists to find."""
    paused = item(section="Next", pr=pr(comments=[]))
    assert next_action(paused).kind == "wait"
    assert stalls(paused) == ["CI green and open for review, but no Lead or Tester verdict"]
    assert in_flight([paused]) == [paused]


def test_every_comment_is_asked_for_not_the_first_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Page one holds 30. The 31st verdict going unread re-dispatches for ever."""
    asked: list[list[str]] = []

    def gh(args: list[str]) -> str:
        asked.append(args)
        return "[]"

    monkeypatch.setattr(orchestrate, "_gh", gh)
    assert fetch_comments(29, "TokenFruit/area54") == []
    assert asked == [
        ["api", "--paginate", "repos/TokenFruit/area54/issues/29/comments"],
        ["api", "--paginate", "repos/TokenFruit/area54/pulls/29/reviews"],
    ]


def test_a_merged_pr_is_read_off_its_branch_like_an_open_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The signal that was unreadable: `fetch` only ever asked for open PRs."""
    items = fetched(
        monkeypatch,
        tmp_path,
        branches="tf-019-escalation-build\ntf-019-design",
        merged_prs=[
            {"number": 20, "headRefName": "tf-019-escalation-contract"},
            {"number": 23, "headRefName": "tf-019-escalation-build"},
            {"number": 28, "headRefName": "chore/roadmap-orchestrator"},
        ],
    )
    assert [(i.tf, i.merged_pr) for i in items] == [("TF-019", 23)]


def test_one_pr_on_an_item_is_the_item_s_pr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    items = fetched(monkeypatch, tmp_path, [{"number": 29, "headRefName": "tf-021-x", "body": ""}])
    assert [(i.tf, i.pr.get("number")) for i in items] == [("TF-021", 29)]


# --- which ADR belongs to which item -----------------------------------------


def _adr(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "docs" / "adr" / name
    path.write_text(text, encoding="utf-8")
    return path


def test_an_adr_is_claimed_by_the_line_that_states_what_it_implements(tmp_path: Path) -> None:
    _adr(tmp_path, "0002-escalation.md", "# ADR-0002\n\n**Implements:** TF-019 — the contract\n")
    assert adr_items(tmp_path) == {"19"}


def test_an_adr_that_merely_mentions_an_item_does_not_claim_it(tmp_path: Path) -> None:
    """One cross-reference sentence would otherwise delete the Architect's stage."""
    _adr(
        tmp_path,
        "0002-escalation.md",
        "# ADR-0002\n\n**Implements:** TF-019\n\n## Alternatives\n\nThis supersedes the "
        "transcript approach proposed for TF-020.\n",
    )
    assert adr_items(tmp_path) == {"19"}


def test_one_adr_may_state_several_items(tmp_path: Path) -> None:
    _adr(tmp_path, "0003-two.md", "**Implements:** TF-016 and TF-017\n")
    assert adr_items(tmp_path) == {"16", "17"}


def test_no_adr_directory_claims_nothing(tmp_path: Path) -> None:
    assert adr_items(tmp_path) == set()


# --- what is in flight ------------------------------------------------------


def test_shipped_items_with_no_open_pr_drop_out() -> None:
    shipped = item(spec_status="Shipped", pr={})
    assert in_flight([shipped, item()]) == [item()]


def test_a_shipped_spec_with_an_open_pr_stays_in_flight() -> None:
    shipped = item(spec_status="Shipped")
    assert in_flight([shipped]) == [shipped]


def test_every_roadmap_section_is_read_and_named(tmp_path: Path) -> None:
    """A `- [x]` line under `Done` is finished. A `- [ ]` line is exactly the opposite."""
    roadmap(tmp_path)
    assert roadmap_sections(tmp_path) == {
        "21": "Now",
        "3": "Now",
        "20": "Next",
        "19": "Done",
        "9": "Done",
    }


def test_a_roadmap_that_is_not_there_places_nothing(tmp_path: Path) -> None:
    assert roadmap_sections(tmp_path) == {}


def test_an_unticked_line_under_done_is_half_written_not_finished(tmp_path: Path) -> None:
    roadmap(tmp_path, "# Roadmap\n\n## Done\n\n- [ ] TF-021 — not actually shipped\n")
    assert roadmap_sections(tmp_path) == {"21": "Now"}


def test_a_done_item_is_not_in_flight_whatever_a_leftover_branch_says() -> None:
    """The TF-019 defect: two undeleted branches reported shipped work as Building."""
    shipped = item(spec_status="Approved", branch="tf-019-design", section="Done", pr={})
    assert in_flight([shipped]) == []


def test_done_outranks_an_open_pr_too() -> None:
    assert in_flight([item(section="Done")]) == []


def test_an_item_the_roadmap_has_not_ticked_off_stays_in_flight() -> None:
    assert in_flight([item()]) == [item()]


def test_a_branch_left_behind_by_a_merge_is_not_work() -> None:
    """A merged PR's branch carries a TF number and nothing else. Not in flight."""
    stale = item(spec_status=None, pr={})
    assert in_flight([stale]) == []
