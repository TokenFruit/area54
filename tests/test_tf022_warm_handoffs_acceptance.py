"""TF-022 acceptance tests — warm handoffs.

Written from the roadmap line and the PR body, before reading the
implementation. TF-022 has no spec and no ``states.md`` by CPO decision, so the
criteria are derived from:

    "Every handoff is a cold start. Each agent run re-reads the repo from
     scratch, so a six-round review re-reads the same files six times.
     `claude --resume` and `--agents` already exist; we never used them"

plus the behavioural claims the PR makes for itself.

These tests are offline by construction: every one of them injects a temporary
``store`` directory rather than touching ``~/.claude/projects``, and none of
them invokes the ``claude`` binary.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tools.agents import (
    SESSION_STORE,
    Agent,
    cli_invocation,
    load_agents,
    session_flags,
    session_id,
)


@pytest.fixture
def agent() -> Agent:
    """One real agent definition, to build argv from."""
    return sorted(load_agents(), key=lambda a: a.name)[0]


def _store_with(tmp_path: Path, cwd: Path, session: str, contents: str = "{}\n") -> Path:
    """Create a store containing a transcript for *session* under *cwd*."""
    import re

    munged = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    d = tmp_path / munged
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{session}.jsonl").write_text(contents)
    return tmp_path


# --------------------------------------------------------------------------
# AC3 — session_id is a pure, deterministic derivation
# --------------------------------------------------------------------------


def test_tf022_ac3_same_repo_item_and_role_give_the_same_session_id() -> None:
    a = session_id("TokenFruit/area54", "TF-022", "lead")
    b = session_id("TokenFruit/area54", "TF-022", "lead")
    assert a == b


def test_tf022_ac3_session_id_is_a_valid_uuid() -> None:
    got = session_id("TokenFruit/area54", "TF-022", "lead")
    assert str(uuid.UUID(got)) == got, f"{got!r} is not a canonical UUID string"


@pytest.mark.parametrize(
    "other",
    [
        ("TokenFruit/area53", "TF-022", "lead"),  # different repo
        ("TokenFruit/area54", "TF-021", "lead"),  # different item
        ("TokenFruit/area54", "TF-022", "tester"),  # different role
    ],
)
def test_tf022_ac3_a_different_repo_item_or_role_gives_a_different_session(
    other: tuple[str, str, str],
) -> None:
    """Each role gets its own session on its own item — the whole point.

    A Lead and a Tester sharing a session would each see the other's
    conversation, which is exactly the separation the team's design rests on.
    """
    base = session_id("TokenFruit/area54", "TF-022", "lead")
    assert session_id(*other) != base


def test_tf022_ac3_deriving_a_session_id_writes_nothing() -> None:
    """ "Same inputs, same id, nothing stored." No state file was added."""
    before = set(SESSION_STORE.glob("**/*")) if SESSION_STORE.exists() else set()
    session_id("TokenFruit/area54", "TF-999", "lead")
    after = set(SESSION_STORE.glob("**/*")) if SESSION_STORE.exists() else set()
    assert before == after


# --------------------------------------------------------------------------
# AC4 / AC6 — session_flags picks create vs resume from the store
# --------------------------------------------------------------------------


def test_tf022_ac4_no_transcript_means_create(tmp_path: Path) -> None:
    cwd = Path("/repo/area54")
    assert session_flags("abc", cwd, store=tmp_path) == ["--session-id", "abc"]


def test_tf022_ac4_an_existing_transcript_means_resume(tmp_path: Path) -> None:
    cwd = Path("/repo/area54")
    store = _store_with(tmp_path, cwd, "abc")
    assert session_flags("abc", cwd, store=store) == ["--resume", "abc"]


def test_tf022_ac6_a_transcript_for_a_different_cwd_does_not_count(tmp_path: Path) -> None:
    """The same id under another project must not be resumed into this one."""
    store = _store_with(tmp_path, Path("/repo/other"), "abc")
    assert session_flags("abc", Path("/repo/area54"), store=store) == ["--session-id", "abc"]


def test_tf022_ac6_a_different_session_in_the_same_cwd_does_not_count(tmp_path: Path) -> None:
    store = _store_with(tmp_path, Path("/repo/area54"), "other-session")
    assert session_flags("abc", Path("/repo/area54"), store=store) == ["--session-id", "abc"]


def test_tf022_ac6_paths_with_unusual_characters_are_munged_not_crashed(tmp_path: Path) -> None:
    """Spaces, dots and unicode in a repo path must still resolve to a store dir."""
    cwd = Path("/Users/p/My Projects/area 54.v2/naïve")
    store = _store_with(tmp_path, cwd, "abc")
    assert session_flags("abc", cwd, store=store) == ["--resume", "abc"]


def test_tf022_ac6_a_missing_store_root_means_create(tmp_path: Path) -> None:
    """A machine that has never run the CLI has no ~/.claude/projects at all."""
    absent = tmp_path / "never-created"
    assert session_flags("abc", Path("/repo/area54"), store=absent) == ["--session-id", "abc"]


def test_tf022_ac6_an_empty_transcript_is_still_treated_as_resumable(tmp_path: Path) -> None:
    """Documents current behaviour: existence alone decides.

    An empty ``.jsonl`` is a session that was created and never written to.
    Whether ``--resume`` survives that is verified live, separately.
    """
    store = _store_with(tmp_path, Path("/repo/area54"), "abc", contents="")
    assert session_flags("abc", Path("/repo/area54"), store=store) == ["--resume", "abc"]


def test_tf022_ac6_a_corrupt_transcript_is_still_treated_as_resumable(tmp_path: Path) -> None:
    store = _store_with(tmp_path, Path("/repo/area54"), "abc", contents="not json at all\x00\n")
    assert session_flags("abc", Path("/repo/area54"), store=store) == ["--resume", "abc"]


def test_tf022_ac6_a_directory_where_the_transcript_should_be(tmp_path: Path) -> None:
    """A directory named ``<uuid>.jsonl`` is not a transcript."""
    import re

    cwd = Path("/repo/area54")
    munged = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    (tmp_path / munged / "abc.jsonl").mkdir(parents=True)
    assert session_flags("abc", cwd, store=tmp_path) == ["--session-id", "abc"]


# --------------------------------------------------------------------------
# AC1 — with no session, argv is unchanged
# --------------------------------------------------------------------------


def test_tf022_ac1_no_session_adds_no_session_flags_for_any_agent() -> None:
    for a in load_agents():
        argv = cli_invocation(a, "p")
        assert "--session-id" not in argv, a.name
        assert "--resume" not in argv, a.name


def test_tf022_ac1_explicit_none_is_the_same_as_omitting_it() -> None:
    a = sorted(load_agents(), key=lambda x: x.name)[0]
    assert cli_invocation(a, "p") == cli_invocation(a, "p", session=None)


def test_tf022_ac1_executable_is_still_the_third_positional_argument() -> None:
    """The eval runner calls ``cli_invocation(agent, prompt, self.executable)``.

    If ``session`` had been inserted ahead of ``executable``, that call would
    silently pass the executable name as a session id.
    """
    a = sorted(load_agents(), key=lambda x: x.name)[0]
    assert cli_invocation(a, "p", "/custom/claude")[0] == "/custom/claude"


# --------------------------------------------------------------------------
# AC8 — with a session, the flags actually reach argv
# --------------------------------------------------------------------------


def test_tf022_ac8_a_session_puts_exactly_one_of_the_two_flags_in_argv(
    tmp_path: Path, agent: Agent
) -> None:
    argv = cli_invocation(agent, "p", session="abc", cwd=Path("/repo/area54"))
    assert ("--session-id" in argv) ^ ("--resume" in argv)


def test_tf022_ac8_the_session_id_follows_its_flag(agent: Agent) -> None:
    argv = cli_invocation(agent, "p", session="abc", cwd=Path("/repo/area54"))
    flag = "--resume" if "--resume" in argv else "--session-id"
    assert argv[argv.index(flag) + 1] == "abc"


def test_tf022_ac8_passing_a_session_changes_nothing_else_in_argv(agent: Agent) -> None:
    """The session flags are additive: everything else must survive."""
    base = cli_invocation(agent, "p")
    withs = cli_invocation(agent, "p", session="abc", cwd=Path("/repo/area54"))
    flag = "--resume" if "--resume" in withs else "--session-id"
    i = withs.index(flag)
    assert withs[:i] + withs[i + 2 :] == base


# --------------------------------------------------------------------------
# AC2 — the eval runner must stay a cold start
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# AC5 — the store path is a fact about an external system, so pin it to one
# --------------------------------------------------------------------------

_REAL_STORE = SESSION_STORE / "-Users-purnendusingh-Claude-Projects-area-54"


@pytest.mark.skipif(
    not _REAL_STORE.is_dir(), reason="no real CLI session store for this repo on this machine"
)
def test_tf022_ac5_the_derived_store_path_matches_one_the_cli_actually_wrote() -> None:
    """The munging is only correct if it reproduces a directory the CLI made.

    Every other session test builds its fixture with the implementation's own
    ``MUNGED``, so a wrong-but-self-consistent munging passes them all while
    resuming nothing. This is the one test that would notice.
    """
    real = sorted(p.stem for p in _REAL_STORE.glob("*.jsonl"))
    assert real, "store directory exists but holds no transcripts"
    repo = Path("/Users/purnendusingh/Claude/Projects/area-54")
    assert session_flags(real[0], repo) == ["--resume", real[0]]


# --------------------------------------------------------------------------
# Coverage gaps named in the brief
# --------------------------------------------------------------------------


def test_tf022_gap_concurrent_first_dispatch_picks_create_twice(tmp_path: Path) -> None:
    """Two dispatches of one role+item before either has written a transcript.

    Both observe an absent file and both choose ``--session-id``. The CLI exits
    1 with "Session ID ... is already in use" on the loser. Nothing in the
    design serialises this; documented here as the real behaviour.
    """
    cwd = Path("/repo/area54")
    first = session_flags("abc", cwd, store=tmp_path)
    second = session_flags("abc", cwd, store=tmp_path)
    assert first == second == ["--session-id", "abc"]


def test_tf022_gap_renumbering_an_item_silently_starts_a_new_conversation(tmp_path: Path) -> None:
    """An item that changes TF number derives a different id, so the history is
    orphaned rather than migrated. By design, but it is a real loss."""
    store = _store_with(tmp_path, Path("/repo/a"), session_id("r", "TF-022", "lead"))
    assert session_flags(session_id("r", "TF-022", "lead"), Path("/repo/a"), store=store)[0] == (
        "--resume"
    )
    assert session_flags(session_id("r", "TF-023", "lead"), Path("/repo/a"), store=store)[0] == (
        "--session-id"
    )


def test_tf022_ac2_the_eval_runner_passes_no_session() -> None:
    """A trial that resumed the previous trial would score run 2 against run 1's
    context, and the harness would keep reporting numbers while measuring
    nothing."""
    import inspect

    from tools.evals import runner

    src = inspect.getsource(runner)
    assert "session=" not in src, "the eval runner must not pass a session"
    assert "session_id" not in src, "the eval runner must not derive a session"
