#!/usr/bin/env python3
"""Record pipeline events so a run can be accounted for afterwards.

"Why is it taking so long?" had no answer from data, only from commit
timestamps. This writes one line per event to .claude/telemetry.jsonl, from
which stage durations and defect-round counts are recoverable.

Deliberately a hook rather than something an agent calls: telemetry that
depends on the thing being measured remembering to report is telemetry you
cannot trust when it matters.

Never blocks. A failure here must not stop the pipeline — exit 0 always.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

LOG_NAME = ".claude/telemetry.jsonl"
MAX_BYTES = 5 * 1024 * 1024


def log_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(root) / LOG_NAME


def record(payload: dict[str, object]) -> None:
    entry: dict[str, object] = {"ts": time.time()}
    for key in ("hook_event_name", "session_id", "tool_name"):
        if payload.get(key):
            entry[key] = payload[key]

    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        # The agent's identity, wherever this harness happens to put it.
        for key in ("subagent_type", "agent_type", "description"):
            if tool_input.get(key):
                entry[key] = tool_input[key]

    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_BYTES:
        path.unlink()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def main() -> int:
    # Telemetry must never be the thing that stops the pipeline.
    with contextlib.suppress(Exception):
        record(json.load(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
