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
