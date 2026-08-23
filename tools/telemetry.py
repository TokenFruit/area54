"""Read the pipeline's event log and say what a run actually cost.

python -m tools.telemetry
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / ".claude" / "telemetry.jsonl"

#: A gap longer than this ends a run. Pipelines have long silent stretches
#: while a subagent reads; sessions have longer ones while nobody is there.
RUN_GAP_SECONDS = 30 * 60


@dataclass(frozen=True)
class Event:
    ts: float
    kind: str
    agent: str | None


@dataclass(frozen=True)
class Run:
    events: tuple[Event, ...]

    @property
    def started(self) -> float:
        return self.events[0].ts

    @property
    def duration_seconds(self) -> float:
        return self.events[-1].ts - self.events[0].ts

    @property
    def agents(self) -> Counter[str]:
        return Counter(e.agent for e in self.events if e.agent)


def parse_events(path: Path = LOG_PATH) -> list[Event]:
    """Read the log, skipping anything malformed rather than failing."""
    if not path.is_file():
        return []
    events: list[Event] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or "ts" not in raw:
            continue
        events.append(
            Event(
                ts=float(raw["ts"]),
                kind=str(raw.get("hook_event_name") or raw.get("tool_name") or "event"),
                agent=(
                    str(raw["subagent_type"])
                    if raw.get("subagent_type")
                    else str(raw["agent_type"])
                    if raw.get("agent_type")
                    else None
                ),
            )
        )
    return sorted(events, key=lambda e: e.ts)


def group_runs(events: list[Event], gap_seconds: float = RUN_GAP_SECONDS) -> list[Run]:
    """Split a flat event stream into runs on long silences."""
    if not events:
        return []
    runs: list[list[Event]] = [[events[0]]]
    for index in range(1, len(events)):
        event = events[index]
        if event.ts - events[index - 1].ts > gap_seconds:
            runs.append([event])
        else:
            runs[-1].append(event)
    return [Run(events=tuple(r)) for r in runs]


def _hms(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


def render(runs: list[Run]) -> str:
    """Return a summary. Says plainly when there is nothing to report."""
    if not runs:
        return (
            "No telemetry recorded yet.\n"
            "Events are written by .claude/hooks/record_event.py while the pipeline runs."
        )
    lines = [f"{len(runs)} run(s) recorded.\n"]
    for index, run in enumerate(reversed(runs), start=1):
        lines.append(
            f"  Run {len(runs) - index + 1}: {_hms(run.duration_seconds)}, {len(run.events)} events"
        )
        for agent, count in run.agents.most_common():
            lines.append(f"      {agent:20} {count}x")
        if not run.agents:
            lines.append("      (no agent identified in these events)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.telemetry", description=__doc__)
    parser.add_argument(
        "repos",
        nargs="*",
        help="repositories to report on. Defaults to this one.",
    )
    args = parser.parse_args(argv)

    roots = [Path(r).expanduser().resolve() for r in args.repos] or [REPO_ROOT]
    exit_code = 0
    for index, root in enumerate(roots):
        if len(roots) > 1:
            if index:
                print()
            print(f"── {root.name} ──")
        log = root / ".claude" / "telemetry.jsonl"
        if not root.is_dir():
            print(f"::error::{root} is not a directory.")
            exit_code = 1
            continue
        print(render(group_runs(parse_events(log))))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
