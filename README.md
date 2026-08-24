# area54

**A virtual software‑development team, packaged as a Claude Code plugin.**

area54 is eight role‑scoped AI agents, seven slash commands, and a small body of
tooling that carries a feature from a one‑line roadmap entry all the way to a
merged pull request — grooming a spec, designing it, building it, reviewing it,
and merging it — pausing for a human at exactly **two** decision points and
running autonomously everywhere in between.

There is no server, no database, and nothing to host. The whole team executes
inside Claude Code, on a developer's machine or in CI.

> **The team is the product, and it builds itself using itself.** Every change to
> area54 goes through the same seven roles and two gates it ships to everyone
> else. A rule that would make the team unusable makes *this* repo unusable
> first — which is what keeps the rules honest.

For the full design, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## The team

Eight agents in [`agents/`](agents/), each with a fresh context, its own tool
allow‑list, and one job:

| Agent | Job | Output |
| --- | --- | --- |
| `product-owner` | Roadmap item → buildable spec | `docs/specs/` |
| `architect` | Spec → technical decision | `docs/adr/` |
| `designer` | Spec → interaction design | `docs/design/` |
| `builder-backend` | Server implementation + unit tests | branch → draft PR |
| `builder-frontend` | Client implementation + unit tests | branch → draft PR |
| `lead` | Reviews the diff. **Cannot write code.** | PR comments |
| `tester` | Tests from the **spec**, not the code | `tests/` |
| `devops` | Pipeline, merge, release, rollback | Actions, releases |

## How to drive it

You are the operator. You run the commands and make two decisions per feature.

```
/groom  <roadmap item>   → spec          → you approve   ■ Gate 1
/design TF-NNN           → ADR + design
/build  TF-NNN           → code + draft PR
/review <PR>             → Lead + Tester verdicts
                                          → you approve   ■ Gate 2
/ship   <PR>             → merged, tagged, deployed
/status                  → what is in flight, what needs you
```

`/deliver <roadmap item>` runs the whole sequence at once, stopping only at the
two gates.

**Gate 1 — after the spec.** *Is this the right thing to build?* Open questions
are the gate: the team never answers them for you and never proceeds on an
assumption.

**Gate 2 — before merge.** *Is this good enough to ship?* You approve and run
`/ship`; from there a program — not an agent's opinion — decides whether the PR
may merge.

## The four rules that make it work

1. **The team is the product.** area54 is a plugin you install, not a framework
   you wire up. Editing an agent changes the tool you are currently holding.
2. **GitHub is the memory.** Agents are stateless; every handoff leaves a durable
   artifact — an issue, a committed file, a PR, a review comment. Nothing
   important lives in a chat.
3. **The reviewer cannot write code.** The `lead` agent has no edit tools. A
   reviewer that silently patches what it finds destroys the signal.
4. **Gates are code, not judgement.** CI decides whether tests pass. A merge gate
   — a program that queries the PR and exits non‑zero on any failing rule —
   decides whether a PR may merge. A persuasive prompt cannot talk a subprocess
   into passing.

## The gates, made concrete

- **The merge gate** ([`tools/merge_gate.py`](tools/merge_gate.py), on `PATH` as
  `merge-gate`) checks six things before any merge: the PR is not a draft and is
  mergeable; every CI check succeeded **on this exact commit**; the body links a
  spec; a Lead verdict approves with no blockers; a Tester verdict says Pass; and
  both verdicts were **posted after the head commit was made**. On success it
  writes a ten‑minute authorisation for that one PR at that one commit.
- **The shell guard** ([`hooks/guard_bash.py`](hooks/guard_bash.py)) inspects the
  actual command an agent is about to run — not just its prefix — and blocks
  pushes to `main`, force pushes, `git reset --hard`, and any `gh pr merge` that
  is not backed by a live merge‑gate authorisation.

Together they mean an agent cannot merge by deciding it is ready — only by
having actually passed.

## How it reaches a target repo

area54 **is** a Claude Code plugin: [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json)
at the root, with components discovered by convention from `agents/`,
`commands/`, `hooks/`, and `bin/`. The repo is also its own marketplace, so a
target repo installs the team by name and a prompt fix arrives by version bump
rather than by copy‑paste.

```
python -m tools.deploy /path/to/repo
```

That writes just **three files** into the target — the permission list, the
portable constitution, and the PR template — plus the empty directories the team
files its artefacts into. Everything else lives in the plugin.
`.claude/TEAM_VERSION` records which version a repo has; `claude plugin details
area54` shows what actually loaded.

Each target repo keeps its own `CLAUDE.md`: **area54 ships the roles, the repo
supplies the context** — stack, conventions, and test commands are properties of
the product, not of the team.

## Repository layout

```
agents/         8 role prompts            hooks/     shell guard + telemetry recorder
commands/       7 slash commands          bin/       merge-gate, on PATH in every repo
team/TEAM.md    the portable constitution tools/     Python 3.12 tooling + eval harness
docs/           roadmap, ADRs, specs,     tests/     pytest over all of the above
                design, ARCHITECTURE.md   .claude-plugin/  plugin + marketplace manifests
```

## Working on area54

The stack is recorded in [`docs/adr/0001-stack.md`](docs/adr/0001-stack.md):
Python 3.12 tooling over Markdown agent definitions, with no runtime to host.

| Purpose | Command |
| --- | --- |
| Install (dev) | `pip install -e ".[dev]"` |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| Typecheck | `mypy tools tests` |
| Unit tests | `pytest` |
| Validate agents, commands, config | `python tools/validate.py` |
| What is in flight | `python -m tools.orchestrate status --repo <owner/name>` |
| The next action for each item | `python -m tools.orchestrate next --repo <owner/name> [--run]` |
| Behavioural evals | `python -m tools.evals` (live; costs money) |
| Deploy to a repo | `python -m tools.deploy <path>` |

Every change to area54 goes through area54: a branch, a draft PR, the Lead and
Tester, CI, and the merge gate. There is no privileged way in.

Start with [`CLAUDE.md`](CLAUDE.md) — the team constitution — and
[`docs/roadmap.md`](docs/roadmap.md), which is the only input to everything.
