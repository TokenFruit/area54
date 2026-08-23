#!/usr/bin/env python3
"""Block shell commands that would bypass the team's gates.

A permission allowlist matches command *prefixes*, which cannot express "push
anywhere except main": `git push -u origin main` matches an allow rule for
`git push -u origin` and misses a deny rule for `git push origin main`. That
hole was live in this repo's settings until a Lead review found it.

This hook inspects the actual command instead of its prefix. Exit 2 blocks the
call and returns the message to the agent.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master", "trunk"}

#: Must match tools/merge_gate.TOKEN_TTL_SECONDS. Kept here rather than
#: imported: the hook runs in target repos, where tools/ is not deployed.
AUTHORISATION_TTL_SECONDS = 10 * 60


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        # Unparseable quoting: fall back to a coarse split rather than allowing.
        return command.split()


def blocks(command: str) -> str | None:
    """Return why *command* is refused, or None to allow it."""
    # A compound command hides its parts from a prefix matcher; check each.
    for part in re.split(r"&&|\|\||;|\n", command):
        reason = _blocks_single(part.strip())
        if reason:
            return reason
    return None


def _blocks_single(command: str) -> str | None:
    tokens = _tokens(command)
    if len(tokens) < 2:
        return None

    if tokens[0] == "git" and "push" in tokens[:3]:
        if any(t.startswith("--force") or t == "-f" for t in tokens):
            return "force push refused: it can destroy work another agent is holding."
        # Any argument naming a protected branch, in any position and either
        # side of a refspec — `main`, `HEAD:main`, `main:main`, `+main`.
        for token in tokens:
            if token.startswith("-"):
                continue
            for candidate in token.lstrip("+").split(":"):
                if candidate in PROTECTED_BRANCHES:
                    return (
                        f"refusing to push to '{candidate}'. Changes reach a protected "
                        f"branch through a pull request the CPO merges, never a direct "
                        f"push. Push your feature branch and open a PR."
                    )

    if tokens[0] == "gh" and tokens[1:3] == ["pr", "merge"]:
        return _merge_refusal(tokens)

    if tokens[0] == "git" and tokens[1:2] == ["reset"] and "--hard" in tokens:
        return "refusing `git reset --hard`: it discards work that was never committed."

    return None


def _merge_refusal(tokens: list[str]) -> str | None:
    """Refuse a merge unless the gate actually passed for this exact PR.

    Not "unless the agent believes the gate passed". The gate (`merge-gate`, from
    the plugin's bin/) writes a short-lived authorisation naming the PR and head
    SHA; without a valid one
    that names *this* PR, the merge is refused. An agent cannot author the
    authorisation by deciding it deserves one — the gate writes it, and only
    after every rule passed.
    """
    requested = next((t for t in tokens[3:] if t.isdigit()), None)
    if requested is None:
        return "refusing to merge: no PR number given, so no authorisation can match it."

    token = _read_authorisation()
    if token is None:
        return (
            f"refusing to merge PR #{requested}: no valid merge authorisation. "
            f"Run `merge-gate {requested} --repo <owner/name>` first — the plugin puts "
            f"that on PATH, so it resolves wherever the team is installed. "
            f"If it refuses, report that to the CPO rather than working around it."
        )
    if str(token.get("pr")) != requested:
        return (
            f"refusing to merge PR #{requested}: the authorisation on disk is for "
            f"PR #{token.get('pr')}. One gate pass authorises one merge."
        )
    return None


def _read_authorisation() -> dict[str, object] | None:
    """Read a valid, unexpired authorisation written by the merge gate."""
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    path = root / ".claude" / "merge-authorisation.json"
    if not path.is_file():
        return None
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
        issued = float(token.get("issued", 0))
    except (json.JSONDecodeError, OSError, AttributeError, TypeError, ValueError):
        return None
    if not isinstance(token, dict) or time.time() - issued > AUTHORISATION_TTL_SECONDS:
        return None
    return token


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Never block because the hook itself failed to parse.

    # Every shape but "a mapping holding a mapping" is treated as no command.
    # `payload.get(...)` on a list, or `.get("command")` on a null `tool_input`,
    # raises — and a PreToolUse hook that raises is a non-blocking error, so the
    # command it was asked about runs. The guard failing open is the one way it
    # can be worse than absent.
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    command = str(tool_input.get("command", ""))
    if not command:
        return 0

    reason = blocks(command)
    if reason:
        print(f"Blocked by the team's shell guard: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
