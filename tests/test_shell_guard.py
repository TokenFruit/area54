"""Tests for the shell guard hook.

A permission allowlist matches command prefixes, which cannot express "push
anywhere except main". `git push -u origin main` matched an allow rule for
`git push -u origin` and missed the deny rule for `git push origin main`. A
Lead review caught it. These tests exist so it cannot come back.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "guard_bash", Path(__file__).resolve().parent.parent / "hooks" / "guard_bash.py"
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push -u origin main",  # the actual bypass
        "git push --set-upstream origin main",
        "git push origin HEAD:main",
        "git push origin main:main",
        "git push origin +main",
        "git push origin master",
        "git push origin trunk",
        "git push --force origin feature",
        "git push -f origin feature",
        "npm test && git push -u origin main",  # hidden in a compound command
    ],
)
def test_a_push_that_reaches_a_protected_branch_is_blocked(command: str) -> None:
    assert guard.blocks(command) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin tf-001-metadata",
        "git push origin feature/maintenance",  # 'main' as a substring only
        "git push origin domain-fix",
        "npm test",
        "npx tsc --noEmit",
        "git commit -m 'push to main later'",  # the words, not the act
        "git log --oneline",
    ],
)
def test_ordinary_work_is_not_blocked(command: str) -> None:
    assert guard.blocks(command) is None, command


def test_merging_is_blocked() -> None:
    """No agent merges its own work, whatever the allowlist says."""
    assert guard.blocks("gh pr merge 7 --squash") is not None
    assert guard.blocks("gh pr view 7") is None


def test_a_hard_reset_is_blocked() -> None:
    assert guard.blocks("git reset --hard HEAD~1") is not None
    assert guard.blocks("git reset HEAD~1") is None


def test_unparseable_quoting_still_gets_checked() -> None:
    """A broken quote must not become a way through."""
    assert guard.blocks("git push -u origin main 'unclosed") is not None


# --- the guard must not fail open ----------------------------------------


@pytest.mark.parametrize(
    "payload",
    ['{"tool_input": null}', "[]", '"a string"', "null", "{}", '{"tool_input": []}'],
)
def test_a_malformed_payload_does_not_crash_the_guard(payload: str, tmp_path: Path) -> None:
    """A PreToolUse hook that raises is a non-blocking error — the command runs.

    So a crash here is not a crash, it is an unguarded shell. The guard now
    treats every shape but "a mapping holding a mapping" as no command at all.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "hooks" / "guard_bash.py")],
        input=payload,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_a_well_formed_payload_still_blocks(tmp_path: Path) -> None:
    """The other direction: hardening the parser must not disarm the guard."""
    import json as _json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "hooks" / "guard_bash.py")],
        input=_json.dumps({"tool_input": {"command": "git push -u origin main"}}),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "refusing to push to 'main'" in result.stderr


# --- the splitter must not reintroduce the prefix-matcher hole ------------


@pytest.mark.parametrize(
    "command",
    [
        "true | git push origin main",
        "$(git push origin main)",
        "`git push origin main`",
        'bash -c "git push origin main"',
        '/bin/sh -c "git push --force origin feature"',
        'zsh -c "gh pr merge 1 --squash"',
        "env FOO=1 git push origin main",
        "FOO=1 git push origin main",
        'cat x && bash -c "git push origin main"',
    ],
)
def test_a_protected_command_is_refused_wherever_it_sits(command: str) -> None:
    """The guard split on `&& || ; \\n` and required the word at the front.

    That is the same hole as the permission prefix matcher this module was
    written to replace, one level down — and `bash -c "..."` is not exotic, it
    is what an agent reaches for when quoting gets in the way. Every one of
    these ran before.
    """
    assert guard.blocks(command) is not None, command


def test_a_nested_shell_running_something_harmless_is_allowed() -> None:
    """Unwrapping must not turn every nested shell into a refusal."""
    assert guard.blocks('bash -c "npm test"') is None
    assert guard.blocks('sh -c "git push -u origin feature/x"') is None


def test_two_levels_of_real_nesting_are_still_read() -> None:
    """Alternating quotes is how nesting is actually written."""
    assert guard.blocks("""bash -c 'bash -c "git push origin main"'""") is not None
    assert guard.blocks("""bash -c 'bash -c "npm test"'""") is None


def test_the_depth_cap_refuses_rather_than_gives_up() -> None:
    """A backstop, tested at the mechanism rather than through a quoted string.

    Shell quoting does not nest by repetition — `bash -c "bash -c "x""` is not
    two levels — so the cap cannot be reached by piling on quotes. It exists so
    that a shape which *does* recurse ends in a refusal rather than in a return
    to allowed.
    """
    assert guard._blocks_command("npm test", depth=5) is not None
