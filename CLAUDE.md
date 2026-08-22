# Token Fruit — Team Constitution

This file is inherited by every agent on this team. It is the single source of
truth for how we work. If an instruction here conflicts with an agent's own
prompt, this file wins.

## What this repo is

**area54 is a virtual software development team powered by agentic AI**, which
Token Fruit deploys onto its other product repositories — Gempli (`area53`),
alloqo, flozeno, izenesis, and whatever follows.

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
| Behavioural tests | `claude plugin eval` — scored over repeated runs |
| CI | GitHub Actions |
| Runtime | none |

A target repo supplies its own `CLAUDE.md`. area54 ships the roles; the repo
supplies the context.

## Commands

| Purpose | Command |
| ---------- | ------------------- |
| Install | `uv sync` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Typecheck | `uv run mypy --strict .` |
| Unit tests | `uv run pytest -q` |
| Behavioural evals | `claude plugin eval` |
| Build | none — the repo is the plugin |

The Python toolchain is not yet scaffolded; the first Builder to need it creates
`pyproject.toml`. `claude plugin eval` availability on this account is unverified
— DevOps confirms it before CI depends on it.

## Definition of Done

A feature is done when **all** of these are true. No exceptions, no "we'll do it
in a follow-up" unless the CPO says so in writing on the PR.

1. Every acceptance criterion in the spec has a passing automated test.
2. Typecheck, lint, and the full test suite pass in CI — not just locally.
3. The Lead's review has no unresolved findings at severity `blocker` or `major`.
4. Error, empty, and loading states exist for every user-facing surface.
5. No secrets, keys, or credentials in the diff.
6. The PR body links its spec and any ADR it implements.
7. Public functions and non-obvious logic are documented. Obvious code is not.

## Coding standards

- **Match the surrounding code.** Naming, structure, comment density, and idiom
  should be indistinguishable from what's already there. A diff that announces
  itself as written by a different author is a defect.
- **Small, complete units.** A function does one thing. A PR does one feature.
- **Fail loudly.** No silent catches, no swallowed errors, no `catch {}`. If you
  cannot handle an error, let it propagate with context attached.
- **No dead code.** Do not leave commented-out blocks, unused exports, or
  speculative abstractions for features nobody asked for.
- **Types are not optional.** No `any`, no untyped dicts crossing a module
  boundary. If the type is genuinely dynamic, document why.
- **Tests describe behaviour, not implementation.** A test that breaks when you
  rename a private method is a bad test.
- **Dependencies are a liability.** Adding one requires a line in the ADR
  justifying it. Prefer the standard library.

## Git and PR conventions

- Branch: `tf-<issue-number>-<short-slug>` — e.g. `tf-12-wallet-connect`.
- Commit subject: imperative, under 72 chars, no trailing period.
- One logical change per commit. No "fix", "wip", or "address review" commits —
  amend or rebase instead.
- PRs open as **draft**, and are marked ready only when CI is green.
- Never force-push a branch another agent is working on.
- Never commit directly to `main`.

## Handoff rules

Agents do not talk to each other. They read and write files, and the CPO or a
slash command moves work between them. This is deliberate: every handoff must
leave a durable artifact.

| Role          | Reads                              | Writes                    |
| ------------- | ---------------------------------- | ------------------------- |
| Product Owner | `docs/roadmap.md`                  | `docs/specs/TF-NNN.md`    |
| Architect     | the spec                           | `docs/adr/NNNN-*.md`      |
| Designer      | the spec                           | `docs/design/TF-NNN/`     |
| Builder       | spec + ADR + design                | source + unit tests       |
| Lead          | the PR diff + this file            | PR review comments        |
| Tester        | **the spec only** — never the code | `tests/`                  |
| DevOps        | CI config, release history         | workflows, releases       |

## Escalation

If you cannot complete your task as specified — the spec is ambiguous,
contradictory, or technically impossible — **stop and report to the CPO**. Do
not improvise a resolution. Write what you found, what you'd need to proceed,
and stop. Guessing at intent is the most expensive failure mode on this team.

## What agents must never do

- Mark their own work as verified. CI decides whether tests pass.
- Merge their own PR.
- Weaken a test to make it pass.
- Modify CI configuration to skip a failing check.
- Commit secrets, or write real credentials into fixtures.
- Expand scope beyond the spec. Out-of-scope ideas go in the PR body as a
  "Follow-ups" list for the CPO to triage.
