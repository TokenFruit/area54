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
from pathlib import Path, PurePosixPath

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


#: Shells and builtins whose *arguments* are commands rather than data. For
#: these, a quoted argument is a payload to look inside; for everything else a
#: quoted argument is text the shell will not execute.
_COMMAND_TAKING = frozenset({"bash", "sh", "zsh", "dash", "ksh", "env", "eval", "xargs"})

#: Where one command can end and the next begin. Enumerating these was the old
#: mistake — they are used now only to keep unrelated commands from being read
#: as one, never to decide *whether* a command is present.
_SEPARATORS = re.compile(r"[;|&\n(){}]+")

#: Command substitution. Live in unquoted text and — verified against bash —
#: inside double quotes too, which is why a double-quoted argument is not
#: automatically inert.
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _lex(command: str) -> list[tuple[str, str]]:
    """Split *command* into ``(text, quote)`` pieces, quote being ``'``, ``"`` or ``""``.

    Written by hand because `shlex` discards exactly the fact this guard needs:
    whether a piece was quoted, and with which quote. A single-quoted argument
    is inert to the shell; a double-quoted one still runs its substitutions;
    an unquoted one is a command. Those three cannot be told apart afterwards.
    """
    pieces: list[tuple[str, str]] = []
    buffer: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and index + 1 < len(command) and quote != "'":
            buffer.append(command[index + 1])
            index += 2
            continue
        if quote:
            if char == quote:
                pieces.append(("".join(buffer), quote))
                buffer, quote = [], ""
            else:
                buffer.append(char)
        elif char in "\"'":
            if buffer:
                pieces.append(("".join(buffer), ""))
                buffer = []
            quote = char
        else:
            buffer.append(char)
        index += 1
    if buffer:
        # Unterminated quote: keep the text and treat it as live rather than
        # letting a stray quote hide a command.
        pieces.append(("".join(buffer), ""))
    return pieces


def _parts(pieces: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Group lexed pieces into one list per command.

    Separators only count where they are unquoted. Splitting the raw string
    first was what made `--body "… `git push origin main` …"` look like two
    commands, and grouping *after* lexing is what lets each part decide for
    itself whether it is a shell.
    """
    parts: list[list[tuple[str, str]]] = [[]]
    for text, quote in pieces:
        if quote:
            parts[-1].append((text, quote))
            continue
        chunks = _SEPARATORS.split(text)
        parts[-1].append((chunks[0], ""))
        for chunk in chunks[1:]:
            parts.append([(chunk, "")])
    return parts


def _executable_text(command: str, depth: int = 0) -> str:
    """Return the part of *command* the shell would execute as a command.

    Not "the command minus its quotes" — that refuses an agent for writing
    `--body "never run git push origin main"`, which pushes nothing, and the
    refusal is then an accusation that is factually untrue. Not "the unquoted
    part" either: `bash -lc "git push origin main"` hides the whole command in
    one quoted argument, and backticks and `$(…)` **do** run inside double
    quotes — checked against bash rather than assumed.

    So, per command: unquoted text is live; a quoted argument of a shell or
    `eval` is a payload and is live; substitutions inside double quotes are
    live; and single-quoted data is not.
    """
    if depth > 4:  # Deeper than any quoting workaround; treat as opaque.
        return command

    live: list[str] = []
    for part in _parts(_lex(command)):
        leading = next((text for text, quote in part if not quote and text.strip()), "")
        head = _tokens(leading)
        while head and _ASSIGNMENT.match(head[0]):
            head = head[1:]
        # Decided per part, not for the whole string: in
        # `cat x && bash -c "…"` the first command is not a shell and the
        # second is, and reading the leading word of the whole line got that
        # backwards.
        wraps = bool(head) and PurePosixPath(head[0]).name in _COMMAND_TAKING

        for text, quote in part:
            if not quote:
                live.append(text)
            elif wraps:
                # `bash -lc "…"`, `bash -c -- "…"`, `eval "…"`: the argument is
                # a command however the flag before it was spelled, so no flag
                # needs enumerating.
                live.append(_executable_text(text, depth + 1))
            elif quote == '"':
                for outer, inner in _SUBSTITUTION.findall(text):
                    live.append(_executable_text(outer or inner, depth + 1))
        live.append("\n")

    joined = " ".join(live)
    for outer, inner in _SUBSTITUTION.findall(joined):
        joined += " " + _executable_text(outer or inner, depth + 1)
    return joined


def blocks(command: str) -> str | None:
    """Return why *command* is refused, or None to allow it.

    Three rounds of review broke the previous shape twice. It split the string
    into parts and asked whether each part *began* with a protected word, so
    every separator and every wrapper had to be enumerated — a blocklist over an
    unbounded grammar, and `&`, `eval`, `bash -lc`, `bash -c --`, `env -i` and
    `{ …; }` each walked through the gaps in turn.

    This asks a different question: is there a `git` or a `gh` **anywhere** in
    the text the shell will execute? Where it sits, and what put it there, stop
    mattering.
    """
    text = _executable_text(command)
    for part in _SEPARATORS.split(text):
        tokens = _tokens(part)
        for index, token in enumerate(tokens):
            name = PurePosixPath(token).name
            if name not in ("git", "gh"):
                continue
            reason = _blocks_invocation(name, tokens[index + 1 :])
            if reason:
                return reason
    return None


#: `FOO=1 git push origin main` is a plain shell prefix, and what `env FOO=1 …`
#: reduces to. Stripping it covers both, and the form written without `env`.
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")

#: A fully-qualified ref naming a branch. `git push origin HEAD:refs/heads/main`
#: pushes to `main`, and comparing bare names never saw it. Stripped as a
#: prefix, not by taking the last path segment — a branch genuinely called
#: `feature/main` is not `main`.
_REF_PREFIX = re.compile(r"^refs/(?:heads|remotes/[^/]+)/")


def _branch_names(token: str) -> list[str]:
    """Return every branch a push argument could be naming."""
    return [_REF_PREFIX.sub("", side) for side in token.lstrip("+").split(":")]


def _blocks_invocation(name: str, rest: list[str]) -> str | None:
    """Decide about a `git`/`gh` invocation from its arguments.

    *rest* is everything after the program name, wherever it was found. Global
    options are not modelled: `git -C . push origin main` used to pass because
    the check required `push` within three tokens of `git`, and pushing the verb
    right is exactly what a global option that takes a value does.
    """
    if name == "git" and "push" in rest:
        if any(t.startswith("--force") or t == "-f" for t in rest):
            return "force push refused: it can destroy work another agent is holding."
        for token in rest:
            if token.startswith("-"):
                continue
            for candidate in _branch_names(token):
                if candidate in PROTECTED_BRANCHES:
                    return (
                        f"refusing to push to '{candidate}'. Changes reach a protected "
                        f"branch through a pull request the CPO merges, never a direct "
                        f"push. Push your feature branch and open a PR."
                    )

    if name == "gh" and rest[:2] == ["pr", "merge"]:
        return _merge_refusal(["gh", *rest])

    if name == "git" and rest[:1] == ["reset"] and "--hard" in rest:
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
