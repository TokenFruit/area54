"""Running an eval case against an agent.

The runner is behind an interface for two reasons. Live runs cost real money
and require the ``claude`` CLI, so the scoring, loading, and reporting must be
testable without either. And the invocation itself is the part most likely to
change, so it is kept small and isolated.
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tools.evals.case import EvalCase


class Runner(Protocol):
    """Runs one trial of one case, and reports what the agent said and touched."""

    def run(self, case: EvalCase, workdir: Path) -> tuple[str, frozenset[str]]:
        """Return the agent's output, and the fixture-relative files it changed."""
        ...


def changed_files(original: Path, working: Path) -> frozenset[str]:
    """Return files that differ between two copies of a fixture."""
    changed: set[str] = set()
    for path in sorted(original.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(original)
        counterpart = working / relative
        if not counterpart.exists() or not filecmp.cmp(path, counterpart, shallow=False):
            changed.add(str(relative))
    for path in sorted(working.rglob("*")):
        if path.is_file():
            relative = path.relative_to(working)
            if not (original / relative).exists():
                changed.add(str(relative))
    return frozenset(changed)


class FakeRunner:
    """A runner that replays scripted results. Used to test the harness itself."""

    def __init__(self, script: Callable[[EvalCase, int], tuple[str, frozenset[str]]]) -> None:
        self._script = script
        self._calls = 0

    def run(self, case: EvalCase, workdir: Path) -> tuple[str, frozenset[str]]:
        result = self._script(case, self._calls)
        self._calls += 1
        return result


class ClaudeCliRunner:
    """Runs a trial by shelling out to the ``claude`` CLI in headless mode.

    .. warning::

       **Unverified.** The ``claude`` CLI is not installed on the machine where
       this was written, so the invocation below has never been executed. Treat
       the flags as a starting point, not a contract: confirm them against
       ``claude --help`` before trusting a green eval run, and fix them here if
       they are wrong. Everything else in this package is tested and does not
       depend on this class being right.
    """

    def __init__(self, executable: str = "claude", timeout_seconds: int = 600) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Whether the CLI can be found at all."""
        return shutil.which(self.executable) is not None

    def run(self, case: EvalCase, workdir: Path) -> tuple[str, frozenset[str]]:
        if not self.is_available():
            raise RuntimeError(
                f"'{self.executable}' is not on PATH. Live eval runs need the Claude Code CLI; "
                f"install it, or run with the fake runner to exercise the harness only."
            )
        prompt = f"Use the {case.agent} subagent for this task.\n\n{case.prompt}"
        completed = subprocess.run(  # noqa: S603
            [self.executable, "-p", prompt],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        return completed.stdout + completed.stderr, frozenset()


def run_trial(case: EvalCase, runner: Runner) -> tuple[str, frozenset[str]]:
    """Copy the fixture somewhere disposable, run one trial, report what changed.

    The agent works on a copy so that a misbehaving agent cannot corrupt the
    fixture for every subsequent trial.
    """
    with tempfile.TemporaryDirectory(prefix=f"eval-{case.name}-") as tmp:
        workdir = Path(tmp) / case.fixture
        shutil.copytree(case.fixture_dir, workdir)
        output, reported = runner.run(case, workdir)
        touched = reported | changed_files(case.fixture_dir, workdir)
        return output, touched
