"""Tests for the pipeline event log and its reporter.

"Why is it taking so long?" had no answer from data. These cover the part that
can be tested deterministically: parsing, run-splitting, and reporting. The
hook payload shape is the harness's, not ours, so the parser is written to skip
what it does not recognise rather than fail on it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from tools.telemetry import Event, group_runs, parse_events, render

_spec = importlib.util.spec_from_file_location(
    "record_event", Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "record_event.py"
)
assert _spec and _spec.loader
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)


def write_log(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "telemetry.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# --- parsing --------------------------------------------------------------


def test_a_missing_log_is_not_an_error() -> None:
    assert parse_events(Path("/nonexistent/telemetry.jsonl")) == []


def test_malformed_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    """A corrupt line must not cost you the rest of the run's history."""
    path = tmp_path / "t.jsonl"
    path.write_text(
        '{"ts": 1.0, "subagent_type": "lead"}\n'
        "not json at all\n"
        '{"no_ts": true}\n'
        '{"ts": 2.0, "subagent_type": "tester"}\n',
        encoding="utf-8",
    )
    events = parse_events(path)
    assert [e.agent for e in events] == ["lead", "tester"]


def test_events_are_sorted_by_time(tmp_path: Path) -> None:
    path = write_log(tmp_path, [{"ts": 5.0}, {"ts": 1.0}, {"ts": 3.0}])
    assert [e.ts for e in parse_events(path)] == [1.0, 3.0, 5.0]


def test_the_agent_is_read_from_either_key(tmp_path: Path) -> None:
    """The harness may name it either way; neither should be silently dropped."""
    path = write_log(
        tmp_path, [{"ts": 1.0, "subagent_type": "lead"}, {"ts": 2.0, "agent_type": "tester"}]
    )
    assert [e.agent for e in parse_events(path)] == ["lead", "tester"]


# --- runs -----------------------------------------------------------------


def test_a_long_silence_starts_a_new_run() -> None:
    events = [
        Event(ts=0, kind="e", agent="lead"),
        Event(ts=60, kind="e", agent="tester"),
        Event(ts=60 + 4000, kind="e", agent="lead"),
    ]
    runs = group_runs(events, gap_seconds=1800)
    assert len(runs) == 2
    assert len(runs[0].events) == 2


def test_a_pipelines_own_quiet_stretches_do_not_split_it() -> None:
    """A subagent reading a codebase is silent for minutes; that is one run."""
    events = [Event(ts=t, kind="e", agent="lead") for t in (0, 600, 1200)]
    assert len(group_runs(events, gap_seconds=1800)) == 1


def test_a_run_reports_its_duration_and_who_worked() -> None:
    events = [
        Event(ts=0, kind="e", agent="product-owner"),
        Event(ts=120, kind="e", agent="lead"),
        Event(ts=180, kind="e", agent="lead"),
    ]
    run = group_runs(events)[0]
    assert run.duration_seconds == 180
    assert run.agents["lead"] == 2


def test_no_events_is_no_runs() -> None:
    assert group_runs([]) == []


# --- reporting ------------------------------------------------------------


def test_an_empty_report_says_so_rather_than_implying_zero_work() -> None:
    assert "No telemetry recorded yet" in render([])


def test_the_report_names_the_agents_and_the_duration() -> None:
    events = [Event(ts=0, kind="e", agent="lead"), Event(ts=125, kind="e", agent="tester")]
    text = render(group_runs(events))
    assert "lead" in text and "tester" in text
    assert "2m05s" in text


# --- the recorder ---------------------------------------------------------


def test_the_recorder_writes_what_it_was_given(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    recorder.record({"hook_event_name": "SubagentStop", "tool_input": {"subagent_type": "lead"}})
    written = json.loads((tmp_path / ".claude" / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert written["subagent_type"] == "lead"
    assert written["hook_event_name"] == "SubagentStop"
    assert "ts" in written


def test_the_recorder_never_raises_on_junk(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Telemetry must never be the thing that stops the pipeline."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    recorder.record({})
    recorder.record({"tool_input": "not a dict"})
    assert (tmp_path / ".claude" / "telemetry.jsonl").is_file()
