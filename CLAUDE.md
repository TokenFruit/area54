# Token Fruit — Team Constitution

This file is inherited by every agent on this team. It is the single source of
truth for how we work. If an instruction here conflicts with an agent's own
prompt, this file wins.

## What this repo is

**area54 is a virtual software development team powered by agentic AI**, which
Token Fruit deploys to work on its products.

**Which repositories it is deployed into is the CPO's call, never inferred.**
area54 is independent of Gempli (`area53`) and is **not** deployed there — they
share the `TokenFruit` org and a naming series, and neither is a dependency.

The team is the product. Read that twice before changing anything: the agents,
commands, and policies in this repo are not scaffolding around the deliverable,
they *are* the deliverable.

This has a consequence that catches people out. This repo is both the team and
the team's first customer — area54 builds itself using itself. When you change
an agent definition here, you are changing the tool you are currently holding.

The human owner acts as Central Product Officer (CPO): sets the roadmap,
approves specs, approves merges. Everything between those gates is autonomous.

## Stack

Decided in [`docs/adr/0001-stack.md`](docs/adr/0001-stack.md). area54 has **no
server, no database, and nothing to host** — it ships as a Claude Code plugin
that executes on a developer's machine or in CI.

| | |
| --- | --- |
| Distribution | Claude Code plugin, from a private marketplace repo |
| Agent artefacts | Markdown with YAML frontmatter; JSON manifest |
| Tooling language | Python 3.12, managed with `uv` |
| Lint / format | `ruff` |
| Types | `mypy --strict` |
| Unit tests | `pytest` — deterministic checks over agent definitions |
| Behavioural tests | `python -m tools.evals` — scored over repeated trials |
| CI | GitHub Actions |
| Runtime | none |

A target repo supplies its own `CLAUDE.md`. area54 ships the roles; the repo
supplies the context.

**How stack decisions get made.** The Architect never simply picks. With no
`docs/adr/0001-stack.md` on disk — a new project — it asks the CPO once whether
the stack is already decided, then either records the CPO's choice as the
Decision and suggests changes separately — each naming a concrete cost, not a
preference — or, if the stack is open, chooses on its own expertise and defends
it against the two strongest alternatives it rejected. Either way the CPO
approves the ADR before it is accepted. **Once that ADR exists the decision is
recorded and the question is not asked again**: the Architect reads it. See
[`.claude/agents/architect.md`](.claude/agents/architect.md).

## Commands

| Purpose | Command |
| ---------- | ------------------- |
| Install | `uv sync` (CI currently uses `pip install -e ".[dev]"`) |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| Typecheck | `mypy tools tests` |
| Unit tests | `pytest` |
| Agent, command and constitution checks | `python tools/validate.py` |
| What is in flight, and what is stalled | `python -m tools.orchestrate status --repo <owner/name>` |
| The next action for each item | `python -m tools.orchestrate next --repo <owner/name> [--run]` |
| Behavioural evals | `python -m tools.evals` (live; costs money) |
| List eval cases | `python -m tools.evals --list` |
| Build | none — the repo is the plugin |
| Deploy to a repo | `python -m tools.deploy <path>` |
| Check a repo is current | `python -m tools.deploy <path> --check` |

The eval harness is tested and its CLI invocation has been executed for real.
Live trials errored before reaching the model while the CLI's OAuth session was
expired; **that session was re-authenticated on 2026-08-23 and live calls now
work**. No trial has been run since, so none has yet completed — the blocker is
gone, the evidence is not yet in. Errored trials are reported as inconclusive,
never as behavioural failures. See `evals/README.md`.

`claude plugin eval` — the CLI's own, better runner — exists but is in early
access and not enabled on this account. Migrate to it when access arrives.

## Team rules

The portable half of this constitution — Definition of Done, coding standards,
git conventions, handoff rules, the defect loop, tool scoping, model pinning,
escalation, and the list of things agents must never do — lives in
[`team/TEAM.md`](team/TEAM.md), because it is **deployed to every target repo**.

Read it as part of this file. It applies here exactly as it applies everywhere
else: area54 is built by the team it ships.

Change a rule there, not here, unless the rule is genuinely specific to area54.
