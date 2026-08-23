"""Tests for the merge gate.

The merge is the one irreversible step. Until now it was gated by an agent
reading its instructions and deciding it was satisfied, which a sufficiently
persuasive prompt satisfies. These tests pin the rules, and — more importantly
— pin that every ambiguous case refuses rather than passes.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from tools.merge_gate import (
    TOKEN_TTL_SECONDS,
    GateError,
    _head_committed_at,
    check_ci_green,
    check_lead_verdict,
    check_mergeable,
    check_not_draft,
    check_spec_linked,
    check_tester_verdict,
    evaluate,
    read_authorisation,
    write_authorisation,
)

_spec = importlib.util.spec_from_file_location(
    "guard_bash", Path(__file__).resolve().parent.parent / "hooks" / "guard_bash.py"
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


#: The head commit, and the two sides of it a verdict can fall on.
COMMITTED = "2026-08-24T12:00:00Z"
AFTER = "2026-08-24T12:05:00Z"
BEFORE = "2026-08-24T11:55:00Z"


def said(body: str, posted: str = AFTER) -> dict[str, object]:
    """One comment or review, as fetch() hands it to the rules."""
    return {"body": body, "posted": posted}


def pr(**overrides: object) -> dict[str, object]:
    """A PR that passes every rule, so each test can break exactly one."""
    data: dict[str, object] = {
        "headRefOid": "abc1234",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "body": "Implements docs/specs/TF-002-robots-and-sitemap.md",
        "head_committed_at": COMMITTED,
        "statusCheckRollup": [
            {"name": "Governance", "conclusion": "SUCCESS"},
            {"name": "Typecheck / Lint / Test", "conclusion": "SUCCESS"},
        ],
        "all_comments": [
            said("## Lead review\n\n**Verdict: Approve.** 0 blockers, 0 majors, 1 minor."),
            said("## Tester report\n\n**Tester verdict: Pass** — 13/13 criteria covered."),
        ],
    }
    data.update(overrides)
    return data


def test_a_clean_pr_passes_every_rule() -> None:
    assert [r.name for r in evaluate(pr()) if not r.passed] == []


# --- each rule refuses what it exists to refuse ----------------------------


def test_a_draft_is_refused() -> None:
    assert not check_not_draft(pr(isDraft=True)).passed


def test_a_conflicted_pr_is_refused() -> None:
    assert not check_mergeable(pr(mergeable="CONFLICTING")).passed


def test_an_unknown_mergeable_state_is_refused() -> None:
    """GitHub returns UNKNOWN while it recomputes. Unknown is not yes."""
    assert not check_mergeable(pr(mergeable="UNKNOWN")).passed


def test_a_failing_check_is_refused() -> None:
    result = check_ci_green(pr(statusCheckRollup=[{"name": "Test", "conclusion": "FAILURE"}]))
    assert not result.passed
    assert "FAILURE" in result.detail


def test_a_pending_check_is_refused() -> None:
    """Still running is not green, and is the state most likely to be misread."""
    assert not check_ci_green(pr(statusCheckRollup=[{"name": "Test", "state": "PENDING"}])).passed


def test_no_checks_at_all_is_refused() -> None:
    """The dangerous case: a repo with no CI would otherwise sail through."""
    result = check_ci_green(pr(statusCheckRollup=[]))
    assert not result.passed
    assert "absence is not a pass" in result.detail


def test_a_pr_with_no_spec_and_no_waiver_is_refused() -> None:
    assert not check_spec_linked(pr(body="just a quick fix")).passed


def test_an_explicit_waiver_is_accepted() -> None:
    assert check_spec_linked(pr(body="No spec: infrastructure change.")).passed


# --- the verdicts ---------------------------------------------------------


def test_a_missing_lead_verdict_is_refused() -> None:
    result = check_lead_verdict(pr(all_comments=[said("Tester verdict: Pass")]))
    assert not result.passed
    assert "no Lead verdict" in result.detail


def test_a_lead_requesting_changes_is_refused() -> None:
    assert not check_lead_verdict(
        pr(all_comments=[said("## Lead\n\n**Verdict: Changes requested** — 1 blocker.")])
    ).passed


def test_a_lead_approval_carrying_a_blocker_is_refused() -> None:
    """An approval that also reports a blocker is a contradiction, not a pass."""
    assert not check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve** — 1 blocker, 0 majors.")])
    ).passed


def test_a_lead_approval_carrying_a_major_is_refused() -> None:
    assert not check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve with minors** — 0 blockers, 2 majors.")])
    ).passed


def test_minors_and_nits_do_not_block() -> None:
    assert check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve with minors** — 0 blockers, 0 majors, 3 minors")])
    ).passed


def test_a_missing_tester_verdict_is_refused() -> None:
    """The failure this gate was built for.

    On TF-002 the Tester passed and reported into a transcript rather than to
    the PR, so a merged change carried a code review and no evidence anyone
    had verified it against its spec.
    """
    result = check_tester_verdict(
        pr(all_comments=[said("**Verdict: Approve.** 0 blockers, 0 majors.")])
    )
    assert not result.passed
    assert "no Tester verdict posted to the PR" in result.detail


def test_a_failing_tester_verdict_is_refused() -> None:
    assert not check_tester_verdict(
        pr(all_comments=[said("## Tester\n\n**Tester verdict: Fail** — 2 defects open.")])
    ).passed


def test_the_latest_verdict_wins() -> None:
    """A later Fail must not be overridden by an earlier Pass."""
    assert not check_tester_verdict(
        pr(
            all_comments=[
                said("Tester verdict: Pass"),
                said("Re-run after the fix. Tester verdict: Fail — regression found."),
            ]
        )
    ).passed


# --- a verdict must postdate the code it is about -------------------------
#
# The gate used to accept approve, push more commits, wait for CI to go green,
# merge. The verdicts described a commit that was no longer the head, so the
# merge was authorised for code nobody had read.


def test_a_lead_verdict_posted_after_the_head_commit_still_passes() -> None:
    """The existing behaviour, pinned: nothing about a current verdict changes."""
    assert check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve.** 0 blockers, 0 majors.", posted=AFTER)])
    ).passed


def test_a_lead_verdict_predating_the_head_commit_is_refused() -> None:
    result = check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve.** 0 blockers, 0 majors.", posted=BEFORE)])
    )
    assert not result.passed
    assert "predates the head commit" in result.detail


def test_a_tester_verdict_posted_after_the_head_commit_still_passes() -> None:
    assert check_tester_verdict(
        pr(all_comments=[said("**Tester verdict: Pass** — 13/13 covered.", posted=AFTER)])
    ).passed


def test_a_tester_verdict_predating_the_head_commit_is_refused() -> None:
    result = check_tester_verdict(
        pr(all_comments=[said("**Tester verdict: Pass** — 13/13 covered.", posted=BEFORE)])
    )
    assert not result.passed
    assert "predates the head commit" in result.detail


def test_a_stale_verdict_does_not_read_like_a_missing_one() -> None:
    """Two different problems. 'Nobody reviewed it' and 'someone reviewed
    something else' need different fixes, so they need different messages."""
    approval = "**Verdict: Approve.** 0 blockers, 0 majors."
    stale = check_lead_verdict(pr(all_comments=[said(approval, posted=BEFORE)]))
    missing = check_lead_verdict(pr(all_comments=[]))
    assert stale.detail != missing.detail

    verdict = "**Tester verdict: Pass**"
    stale_tester = check_tester_verdict(pr(all_comments=[said(verdict, posted=BEFORE)]))
    missing_tester = check_tester_verdict(pr(all_comments=[]))
    assert stale_tester.detail != missing_tester.detail


def test_a_verdict_posted_in_the_same_second_as_the_commit_is_refused() -> None:
    """GitHub stamps to the second, so equal timestamps cannot be ordered.

    Ambiguous is not a pass: the boundary is strictly after.
    """
    assert not check_lead_verdict(
        pr(all_comments=[said("**Verdict: Approve.** 0 blockers, 0 majors.", posted=COMMITTED)])
    ).passed


def test_a_verdict_one_second_after_the_commit_is_accepted() -> None:
    """The other side of the same boundary."""
    assert check_lead_verdict(
        pr(
            all_comments=[
                said("**Verdict: Approve.** 0 blockers, 0 majors.", posted="2026-08-24T12:00:01Z")
            ]
        )
    ).passed


def test_a_later_verdict_rescues_an_earlier_stale_one() -> None:
    """Re-reviewing after the push is exactly what the refusal asks for."""
    approval = "**Verdict: Approve.** 0 blockers, 0 majors."
    assert check_lead_verdict(
        pr(all_comments=[said(approval, posted=BEFORE), said(approval, posted=AFTER)])
    ).passed


# --- a verdict that cannot be dated is refused, not guessed ---------------


def test_a_verdict_with_no_timestamp_is_refused() -> None:
    with pytest.raises(GateError):
        check_lead_verdict(pr(all_comments=[said("**Verdict: Approve.**", posted="")]))


def test_a_verdict_with_an_unreadable_timestamp_is_refused() -> None:
    with pytest.raises(GateError):
        check_tester_verdict(pr(all_comments=[said("**Tester verdict: Pass**", posted="Tuesday")]))


def test_a_verdict_with_no_time_zone_is_refused() -> None:
    """Two clocks, no offset between them, so no ordering worth trusting."""
    with pytest.raises(GateError):
        check_lead_verdict(pr(all_comments=[said("**Verdict: Approve.**", posted="2026-08-24")]))


def test_an_undatable_head_commit_is_refused() -> None:
    with pytest.raises(GateError):
        check_lead_verdict(pr(head_committed_at=""))


def test_a_comment_that_is_not_a_mapping_is_refused() -> None:
    """The old fetch() shape was a bare string. Reading one is a refusal, not a pass."""
    with pytest.raises(GateError):
        check_lead_verdict(pr(all_comments=["**Verdict: Approve.**"]))


def test_a_comment_that_is_not_a_verdict_needs_no_timestamp() -> None:
    """Only verdicts are dated, so ordinary PR chatter cannot jam the gate."""
    assert check_lead_verdict(
        pr(
            all_comments=[
                {"body": "Rebased onto main."},
                said("**Verdict: Approve.** 0 blockers, 0 majors."),
            ]
        )
    ).passed


# --- dating the head commit ------------------------------------------------


def test_the_head_commit_is_dated_by_sha_not_by_position() -> None:
    """The list order is GitHub's; the SHA is the thing the gate is about."""
    commits = [
        {"oid": "abc1234", "committedDate": COMMITTED},
        {"oid": "def5678", "committedDate": AFTER},
    ]
    assert _head_committed_at({"headRefOid": "abc1234", "commits": commits}) == COMMITTED


def test_a_head_commit_missing_from_the_commit_list_is_refused() -> None:
    """Rather than dating the head from some other commit."""
    with pytest.raises(GateError):
        _head_committed_at({"headRefOid": "abc1234", "commits": [{"oid": "def5678"}]})


def test_a_pr_reporting_no_commits_is_refused() -> None:
    with pytest.raises(GateError):
        _head_committed_at({"headRefOid": "abc1234", "commits": []})


# --- the authorisation ----------------------------------------------------


def test_an_authorisation_names_the_pr_and_the_commit(tmp_path: Path) -> None:
    write_authorisation(8, "o/r", "abc1234", tmp_path)
    token = read_authorisation(tmp_path)
    assert token is not None
    assert token["pr"] == 8
    assert token["head"] == "abc1234"


def test_an_expired_authorisation_is_not_read(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "merge-authorisation.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"pr": 8, "repo": "o/r", "head": "a", "issued": time.time() - TOKEN_TTL_SECONDS - 1}
        ),
        encoding="utf-8",
    )
    assert read_authorisation(tmp_path) is None


def test_a_corrupt_authorisation_is_not_read(tmp_path: Path) -> None:
    """Unreadable must mean unauthorised, never authorised."""
    path = tmp_path / ".claude" / "merge-authorisation.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_authorisation(tmp_path) is None


def test_no_authorisation_at_all_is_not_read(tmp_path: Path) -> None:
    assert read_authorisation(tmp_path) is None


# --- the guard enforces it ------------------------------------------------


def write_token(root: Path, pr_number: int, age: float = 0.0) -> None:
    path = root / ".claude" / "merge-authorisation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pr": pr_number, "repo": "o/r", "head": "a", "issued": time.time() - age}),
        encoding="utf-8",
    )


def test_a_merge_without_an_authorisation_is_blocked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert guard.blocks("gh pr merge 8 --squash") is not None


def test_a_merge_with_a_matching_authorisation_is_allowed(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    write_token(tmp_path, 8)
    assert guard.blocks("gh pr merge 8 --squash --delete-branch") is None


def test_one_authorisation_does_not_authorise_a_different_pr(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """One gate pass authorises one merge."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    write_token(tmp_path, 8)
    reason = guard.blocks("gh pr merge 9 --squash")
    assert reason is not None
    assert "for PR #8" in reason


def test_an_expired_authorisation_does_not_permit_a_merge(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    write_token(tmp_path, 8, age=TOKEN_TTL_SECONDS + 60)
    assert guard.blocks("gh pr merge 8 --squash") is not None


def test_a_merge_with_no_pr_number_is_blocked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Nothing to match an authorisation against means nothing is authorised."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    write_token(tmp_path, 8)
    assert guard.blocks("gh pr merge --squash") is not None


def test_pushing_to_main_is_still_blocked_regardless(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A merge authorisation authorises a merge, not a direct push."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    write_token(tmp_path, 8)
    assert guard.blocks("git push -u origin main") is not None


def test_an_unevaluated_gate_is_a_failed_gate() -> None:
    """GateError must never be caught into a pass."""
    assert issubclass(GateError, Exception)
    with pytest.raises(GateError):
        raise GateError("gh missing")
