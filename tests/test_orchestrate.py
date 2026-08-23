"""Tests for the orchestrator.

The published sequence was executed by a human deciding to comply with it, and
in one day six steps were skipped. These pin the dispatch table — every state
in it — and the three stalls that actually happened. Deciding is kept apart
from fetching, so none of this touches a live `gh`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.orchestrate import (
    UNDATEABLE,
    Action,
    Item,
    OrchestratorError,
    changes_requested,
    ci_state,
    dispatch,
    in_flight,
    latest_commit,
    latest_verdict,
    missing_verdicts,
    next_action,
    owning_item,
    roadmap_done,
    stalls,
)

ROADMAP = """# Roadmap

## Now

- [ ] TF-021 — The orchestrator. Nothing checks that a handoff happened

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
    assert not changes_requested(fixed)
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
    assert not changes_requested(reordered)
    verdict = latest_verdict(reordered, "Lead")
    assert verdict is not None and verdict["at"] == "2026-08-24T12:00:00Z"


def test_an_approval_that_predates_the_latest_rejection_does_not_hide_it() -> None:
    later_rejection = pr(
        comments=[
            {"body": LEAD_NO, "at": "2026-08-24T12:00:00Z"},
            {"body": LEAD_OK, "at": "2026-08-24T09:30:00Z"},
        ]
    )
    assert changes_requested(later_rejection)
    assert next_action(item(pr=later_rejection)).stage == "Defect loop"


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


def test_nothing_in_the_table_can_ever_merge() -> None:
    """The merge gate and the shell guard own that step. Nothing here goes near it."""
    for state in (item(spec_status=None), item(has_adr=False), item(pr=pr(isDraft=True))):
        argv = dispatch(next_action(state), state, "TokenFruit/area54")
        assert "merge" not in argv


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


# --- what is in flight ------------------------------------------------------


def test_shipped_items_with_no_open_pr_drop_out() -> None:
    shipped = item(spec_status="Shipped", pr={})
    assert in_flight([shipped, item()]) == [item()]


def test_a_shipped_spec_with_an_open_pr_stays_in_flight() -> None:
    shipped = item(spec_status="Shipped")
    assert in_flight([shipped]) == [shipped]


def test_the_roadmap_done_section_is_read_and_the_open_ones_are_not(tmp_path: Path) -> None:
    """A `- [x]` line is finished. A `- [ ]` line is exactly the opposite."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap.md").write_text(ROADMAP, encoding="utf-8")
    assert roadmap_done(tmp_path) == {"19", "9"}


def test_a_roadmap_with_no_done_section_ticks_nothing_off(tmp_path: Path) -> None:
    assert roadmap_done(tmp_path) == set()


def test_a_done_item_is_not_in_flight_whatever_a_leftover_branch_says() -> None:
    """The TF-019 defect: two undeleted branches reported shipped work as Building."""
    shipped = item(spec_status="Approved", branch="tf-019-design", done=True, pr={})
    assert in_flight([shipped]) == []


def test_done_outranks_an_open_pr_too() -> None:
    assert in_flight([item(done=True)]) == []


def test_an_item_the_roadmap_has_not_ticked_off_stays_in_flight() -> None:
    assert in_flight([item()]) == [item()]


def test_a_branch_left_behind_by_a_merge_is_not_work() -> None:
    """A merged PR's branch carries a TF number and nothing else. Not in flight."""
    stale = item(spec_status=None, pr={})
    assert in_flight([stale]) == []
