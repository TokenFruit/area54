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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tools.agents import load_agents
from tools.evals.case import EvalCase


@dataclass(frozen=True)
class TrialRun:
    """What one invocation produced, before it is scored.

    ``exit_code`` is the difference between "the agent ran and behaved badly"
    and "the run never happened". Conflating those two is how an expired login
    gets read as a behavioural regression.
    """

    output: str
    changed_files: frozenset[str]
    exit_code: int = 0

    @property
    def errored(self) -> bool:
        return self.exit_code != 0


class Runner(Protocol):
    """Runs one trial of one case, and reports what the agent said and touched."""

    def run(self, case: EvalCase, workdir: Path) -> TrialRun:
        """Return the agent's output, the files it changed, and its exit code."""
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

    def __init__(self, script: Callable[[EvalCase, int], TrialRun]) -> None:
        self._script = script
        self._calls = 0

    def run(self, case: EvalCase, workdir: Path) -> TrialRun:
        result = self._script(case, self._calls)
        self._calls += 1
        return result


class ClaudeCliRunner:
    """Runs a trial by invoking the ``claude`` CLI in headless mode.

    The agent under test is applied with ``--append-system-prompt`` and its own
    tool grants, rather than by asking a parent session to delegate to it. Both
    exercise the prompt; this one has no delegation step to fail for reasons
    unrelated to what the case is asking about, and costs one model run instead
    of two.

    Tool grants come from the agent's own frontmatter, so the run is bound by
    the same scoping as production. That matters for the Lead: it holds no
    ``Edit`` or ``Write``, but it does hold ``Bash``, so ``files_unchanged``
    still tests something real — whether it reaches for ``sed`` when told to
    fix the bug it just found.
    """

    def __init__(self, executable: str = "claude", timeout_seconds: int = 600) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Whether the CLI can be found at all."""
        return shutil.which(self.executable) is not None

    def build_command(self, case: EvalCase) -> list[str]:
        """Return the argv for one trial. Separated out so it can be tested."""
        agent = next(a for a in load_agents() if a.name == case.agent)
        return [
            self.executable,
            "-p",
            case.prompt,
            "--append-system-prompt",
            agent.body.strip(),
            "--allowed-tools",
            *agent.tools,
            "--model",
            agent.model,
            "--permission-mode",
            "acceptEdits",
        ]

    def run(self, case: EvalCase, workdir: Path) -> TrialRun:
        if not self.is_available():
            raise RuntimeError(
                f"'{self.executable}' is not on PATH. Live eval runs need the Claude Code CLI; "
                f"install it with: npm install -g @anthropic-ai/claude-code"
            )
        try:
            completed = subprocess.run(  # noqa: S603
                self.build_command(case),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return TrialRun(
                output=f"[timed out after {self.timeout_seconds}s]",
                changed_files=frozenset(),
                exit_code=124,
            )
        return TrialRun(
            output=completed.stdout + completed.stderr,
            changed_files=frozenset(),
            exit_code=completed.returncode,
        )


def run_trial(case: EvalCase, runner: Runner) -> TrialRun:
    """Copy the fixture somewhere disposable, run one trial, report what changed.

    The agent works on a copy so that a misbehaving agent cannot corrupt the
    fixture for every subsequent trial.
    """
    with tempfile.TemporaryDirectory(prefix=f"eval-{case.name}-") as tmp:
        workdir = Path(tmp) / case.fixture
        shutil.copytree(case.fixture_dir, workdir)
        run = runner.run(case, workdir)
        touched = run.changed_files | changed_files(case.fixture_dir, workdir)
        return TrialRun(output=run.output, changed_files=touched, exit_code=run.exit_code)
