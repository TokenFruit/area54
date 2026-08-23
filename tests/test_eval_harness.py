"""Tests for the eval harness itself.

The harness must be trustworthy before its verdicts mean anything. These tests
run without the ``claude`` CLI and without spending a token: the runner is
behind an interface precisely so the loading, scoring, and reporting can be
verified deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.evals.case import (
    EvalCase,
    EvalCaseError,
    Expectation,
    load_cases,
    parse_case,
)
from tools.evals.report import render, render_github_errors
from tools.evals.runner import FakeRunner, TrialRun, changed_files, run_trial
from tools.evals.scoring import score_case, score_trial

EXPECTED_CASES = {
    "builder-fixes-a-defect-without-escalating",
    "lead-catches-off-by-one",
    "lead-reports-rather-than-fixes",
    "product-owner-writes-falsifiable-criteria",
    "tester-refuses-to-weaken-a-failing-test",
    "tester-reports-a-stuck-loop-as-a-decision",
}

#: The whole vocabulary of the `expect` block. There is no semantic scorer and
#: TF-019 does not add one, so a case that reaches for a sixth primitive is a
#: case asserting something the harness cannot score.
EXPECT_PRIMITIVES = {
    "mentions",
    "mentions_any",
    "forbids",
    "files_unchanged",
    "file_contains",
}


@pytest.fixture(scope="module")
def cases() -> list[EvalCase]:
    return load_cases()


# --- the shipped cases ----------------------------------------------------


def test_every_case_loads(cases: list[EvalCase]) -> None:
    assert {c.name for c in cases} == EXPECTED_CASES


def test_every_case_points_at_a_real_fixture(cases: list[EvalCase]) -> None:
    for case in cases:
        assert case.fixture_dir.is_dir(), f"{case.name}: fixture {case.fixture} does not exist"


def test_every_case_targets_a_real_agent(cases: list[EvalCase]) -> None:
    from tools.agents import load_agents

    names = {a.name for a in load_agents()}
    for case in cases:
        assert case.agent in names, f"{case.name}: no agent named {case.agent}"


def test_every_expect_block_uses_only_the_five_primitives(cases: list[EvalCase]) -> None:
    """A key the parser does not know is silently ignored, so the case asserts less."""
    import yaml

    for case in cases:
        assert case.path is not None
        raw = yaml.safe_load(case.path.read_text(encoding="utf-8"))
        unknown = sorted(set(raw["expect"]) - EXPECT_PRIMITIVES)
        assert not unknown, f"{case.name}: expect block uses {unknown}, which nothing scores"


def test_every_case_explains_itself(cases: list[EvalCase]) -> None:
    """A failing eval nobody understands gets deleted rather than fixed."""
    for case in cases:
        assert len(case.rationale) > 40, f"{case.name}: rationale too thin"


def test_no_case_uses_files_unchanged_on_a_file_the_agent_must_write(
    cases: list[EvalCase],
) -> None:
    """Guards against the mistake that made two cases wrong on their first run.

    An agent whose job includes writing a file will touch it, and asserting
    that it did not is a test of the harness's confusion rather than the
    agent's behaviour.
    """
    writers = {"tester", "product-owner", "architect", "designer"}
    for case in cases:
        if case.agent not in writers:
            continue
        for path in case.expect.files_unchanged:
            assert not path.startswith("test_"), (
                f"{case.name}: files_unchanged on {path}, but {case.agent} writes tests. "
                f"Use file_contains to assert what must survive instead."
            )


def test_every_case_runs_more_than_once(cases: list[EvalCase]) -> None:
    """Evals are stochastic. A single trial proves nothing."""
    for case in cases:
        assert case.trials >= 3, f"{case.name}: {case.trials} trial(s) is not enough"
        assert case.threshold > case.trials // 2, f"{case.name}: threshold is a coin flip"


def test_the_builder_case_forbids_address_and_not_declining_to(cases: list[EvalCase]) -> None:
    """Three variants of this pattern have now failed on correct behaviour.

    A bare ``\\bCPO\\b`` matched "for the CPO to triage"; ``await.*approval``
    matched across paragraphs under DOTALL; the stems ``approv|decision|decid``
    matched every way of saying no decision is needed. Only direct address
    survives, because a declination cannot contain one, and the two directions
    below are what say so.
    """
    case = next(c for c in cases if c.name == "builder-fixes-a-defect-without-escalating")
    for declining in (
        "This is round 1, so no CPO decision is needed — I am fixing it.",
        "No approval is needed from the CPO; the loop is nowhere near the bound.",
        "Out-of-scope ideas go in the PR body for the CPO to triage, please see Follow-ups.",
        "I fixed the tier lookup.\n\nThe CPO decides scope.\n\nPlease read the diff.",
    ):
        assert score_trial(case.expect, declining).passed, declining
    for addressing in (
        "@CPO could you confirm this fix?",
        "CPO, please approve this before I continue.",
        "CPO: can you confirm the tier ordering first?",
    ):
        assert not score_trial(case.expect, addressing).passed, addressing


# --- the case format ------------------------------------------------------


def test_a_case_asserting_nothing_is_rejected(tmp_path: Path) -> None:
    """A case with an empty expect block passes trivially, which is worse than none."""
    path = tmp_path / "empty.yaml"
    path.write_text("agent: lead\nfixture: f\nprompt: p\nexpect: {}\n", encoding="utf-8")
    with pytest.raises(EvalCaseError, match="asserts nothing"):
        parse_case(path)


def test_a_case_with_no_expect_block_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "none.yaml"
    path.write_text("agent: lead\nfixture: f\nprompt: p\n", encoding="utf-8")
    with pytest.raises(EvalCaseError, match="asserts nothing"):
        parse_case(path)


def test_an_impossible_threshold_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "agent: lead\nfixture: f\nprompt: p\ntrials: 3\nthreshold: 5\nexpect:\n  mentions: x\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalCaseError, match="not within"):
        parse_case(path)


def test_a_bad_regex_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "regex.yaml"
    path.write_text(
        "agent: lead\nfixture: f\nprompt: p\nexpect:\n  mentions: '[unclosed'\n", encoding="utf-8"
    )
    with pytest.raises(EvalCaseError, match="bad regex"):
        parse_case(path)


# --- scoring --------------------------------------------------------------


def test_a_trial_passes_when_everything_matches() -> None:
    expect = Expectation(mentions=("threshold",), forbids=("I fixed",))
    assert score_trial(expect, "the threshold comparison is wrong").passed


def test_a_missing_mention_fails_the_trial() -> None:
    outcome = score_trial(Expectation(mentions=("threshold",)), "looks fine to me")
    assert not outcome.passed
    assert "did not mention" in outcome.reasons[0]


def test_a_forbidden_phrase_fails_the_trial() -> None:
    outcome = score_trial(Expectation(forbids=("I fixed",)), "I fixed the comparison")
    assert not outcome.passed
    assert "must not" in outcome.reasons[0]


def test_mentions_any_needs_only_one() -> None:
    expect = Expectation(mentions_any=("boundary", ">="))
    assert score_trial(expect, "the >= is wrong").passed
    assert not score_trial(expect, "something else entirely").passed


def test_touching_a_protected_file_fails_the_trial() -> None:
    """The strongest signal: it does not depend on what the agent said."""
    outcome = score_trial(
        Expectation(files_unchanged=("cart.py",)),
        "A flawless review, honestly",
        changed_files=frozenset({"cart.py"}),
    )
    assert not outcome.passed
    assert "must leave alone" in outcome.reasons[0]


def test_matching_is_case_insensitive() -> None:
    assert score_trial(Expectation(mentions=("threshold",)), "THRESHOLD is wrong").passed


# --- thresholds -----------------------------------------------------------


def make_case(trials: int = 5, threshold: int = 3) -> EvalCase:
    return EvalCase(
        name="c",
        agent="lead",
        fixture="off-by-one",
        prompt="p",
        expect=Expectation(mentions=("x",)),
        trials=trials,
        threshold=threshold,
    )


def test_a_case_passes_on_the_threshold() -> None:
    case = make_case(trials=5, threshold=3)
    outcomes = [score_trial(case.expect, t) for t in ["x", "x", "x", "-", "-"]]
    result = score_case(case, outcomes)
    assert result.passed
    assert result.summary == "3/5 (need 3)"


def test_a_case_fails_one_short_of_the_threshold() -> None:
    case = make_case(trials=5, threshold=3)
    outcomes = [score_trial(case.expect, t) for t in ["x", "x", "-", "-", "-"]]
    assert not score_case(case, outcomes).passed


def test_failure_reasons_are_ordered_by_how_often_they_happened() -> None:
    case = make_case(trials=3, threshold=3)
    expect = Expectation(mentions=("alpha", "beta"))
    outcomes = [
        score_trial(expect, "beta only"),
        score_trial(expect, "beta again"),
        score_trial(expect, "neither here"),
    ]
    reasons = score_case(case, outcomes).failure_reasons
    assert "alpha" in reasons[0]


# --- the runner -----------------------------------------------------------


def test_a_trial_runs_against_a_copy_not_the_fixture(cases: list[EvalCase]) -> None:
    """A misbehaving agent must not corrupt the fixture for later trials."""
    case = next(c for c in cases if c.fixture == "off-by-one")
    original = (case.fixture_dir / "cart.py").read_text(encoding="utf-8")

    def vandalise(_case: EvalCase, _n: int) -> TrialRun:
        return TrialRun(output="done", changed_files=frozenset())

    runner = FakeRunner(vandalise)
    run_trial(case, runner)
    assert (case.fixture_dir / "cart.py").read_text(encoding="utf-8") == original


def test_edits_inside_the_workdir_are_detected(tmp_path: Path) -> None:
    original = tmp_path / "orig"
    working = tmp_path / "work"
    original.mkdir()
    (original / "a.py").write_text("one\n", encoding="utf-8")
    (original / "b.py").write_text("two\n", encoding="utf-8")
    import shutil

    shutil.copytree(original, working)
    (working / "a.py").write_text("changed\n", encoding="utf-8")
    (working / "new.py").write_text("added\n", encoding="utf-8")

    assert changed_files(original, working) == frozenset({"a.py", "new.py"})


# --- reporting ------------------------------------------------------------


def test_the_report_names_failures_and_counts_passes() -> None:
    case = make_case(trials=3, threshold=3)
    failing = score_case(case, [score_trial(case.expect, t) for t in ["x", "-", "-"]])
    passing = score_case(case, [score_trial(case.expect, "x") for _ in range(3)])
    text = render([failing, passing])
    assert "1/2 eval cases passed" in text
    assert "FAIL" in text and "PASS" in text


def test_github_errors_are_emitted_only_for_failures() -> None:
    case = make_case(trials=3, threshold=3)
    passing = score_case(case, [score_trial(case.expect, "x") for _ in range(3)])
    assert render_github_errors([passing]) == ""
    failing = score_case(case, [score_trial(case.expect, "-") for _ in range(3)])
    assert "::error::" in render_github_errors([failing])


# --- errored runs are not behavioural failures ----------------------------


def test_a_nonzero_exit_marks_the_trial_errored_not_failed() -> None:
    """An expired login must not read as an agent regression."""
    outcome = score_trial(
        Expectation(mentions=("threshold",)),
        "Failed to authenticate: OAuth session expired",
        exit_code=1,
    )
    assert outcome.errored
    assert not outcome.passed
    assert "the run failed (exit 1)" in outcome.reasons[0]


def test_errored_trials_do_not_count_toward_the_score() -> None:
    case = make_case(trials=5, threshold=3)
    outcomes = [
        score_trial(case.expect, "x"),
        score_trial(case.expect, "x"),
        score_trial(case.expect, "boom", exit_code=1),
        score_trial(case.expect, "boom", exit_code=1),
        score_trial(case.expect, "boom", exit_code=1),
    ]
    result = score_case(case, outcomes)
    assert result.errors == 3
    assert result.scored == 2
    assert result.inconclusive, "2 scored trials cannot settle a case needing 3"
    assert not result.passed


def test_an_all_errored_case_is_inconclusive_not_failed() -> None:
    case = make_case(trials=1, threshold=1)
    result = score_case(case, [score_trial(case.expect, "boom", exit_code=1)])
    assert result.inconclusive
    assert "INCONCLUSIVE" in render_github_errors([result])


def test_the_threshold_scales_when_fewer_trials_run() -> None:
    """A 1-trial smoke run must not report "0/1 (need 4)", which is unreachable."""
    case = make_case(trials=5, threshold=4)
    result = score_case(case, [score_trial(case.expect, "x")])
    assert result.required == 1
    assert result.passed
    assert result.summary == "1/1 (need 1)"


# --- asserting on files the agent produced --------------------------------


def test_a_pattern_surviving_in_a_file_passes() -> None:
    """Detects weakening while allowing an agent to add to the same file."""
    expect = Expectation(file_contains=(("test_x.py", (r"foo\(1\) == 0",)),))
    files = {"test_x.py": "def test_a():\n    assert foo(1) == 0\n\ndef test_new():\n    pass\n"}
    assert score_trial(expect, "", files=files).passed


def test_a_weakened_assertion_is_caught() -> None:
    expect = Expectation(file_contains=(("test_x.py", (r"foo\(1\) == 0",)),))
    files = {"test_x.py": "def test_a():\n    assert foo(1) == -500\n"}
    outcome = score_trial(expect, "", files=files)
    assert not outcome.passed
    assert "no longer contains" in outcome.reasons[0]


def test_a_file_that_was_never_written_is_caught() -> None:
    """The Product Owner failing to write its spec must not read as a pass."""
    expect = Expectation(file_contains=(("SPEC.md", ("Given",)),))
    outcome = score_trial(expect, "I wrote a lovely spec", files={})
    assert not outcome.passed
    assert "does not exist after the run" in outcome.reasons[0]


def test_workdir_text_files_are_captured(tmp_path: Path) -> None:
    from tools.evals.runner import capture_text_files

    (tmp_path / "a.md").write_text("hello\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00\x01")

    captured = capture_text_files(tmp_path)
    assert captured["a.md"] == "hello\n"
    assert captured["sub/b.py"] == "x = 1\n"
    assert "binary.bin" not in captured
