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
import re
import shlex
import sys

PROTECTED_BRANCHES = {"main", "master", "trunk"}


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
        return (
            "refusing to merge. Merging is the CPO's decision and no agent merges "
            "its own work. Report at the gate instead."
        )

    if tokens[0] == "git" and tokens[1:2] == ["reset"] and "--hard" in tokens:
        return "refusing `git reset --hard`: it discards work that was never committed."

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Never block because the hook itself failed to parse.

    command = str(payload.get("tool_input", {}).get("command", ""))
    if not command:
        return 0

    reason = blocks(command)
    if reason:
        print(f"Blocked by the team's shell guard: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
