# ADR-0001: Technical stack

**Status:** Proposed
**Implements:** TF-001 — "Decide the technical stack"
**Supersedes:** none

## Context

area54 is a **virtual software development team powered by agentic AI**,
deployed to work on software products. The team is the product. Its
operator is the CPO, who decides which repositories it is deployed into.

Deployment targets are named by the CPO, never inferred.

This makes the conventional stack question mostly inapplicable. There is no
server, no database, no browser, no user accounts, and nothing to host. What
area54 ships is a set of agent definitions, commands, and policy files that
execute inside Claude Code on a developer's machine or in CI.

So the real decisions are three, and none of them are "which web framework":

1. **How does the team get installed into a target repo, and stay updated?**
2. **What language do the supporting tools use** — validators, installers, and
   the eval harness?
3. **How do you test a team made of prompts?**

The CPO confirmed the stack is genuinely open (Path 2), so this ADR chooses.

Two existing stacks were weighed as defaults. These are cited as **prior art for
tooling only** — where a toolchain has already been proven to work — and imply
nothing about where area54 gets deployed:
- A sibling Python service: FastAPI, Celery, `mypy --strict`, 105 tests.
- A sibling TypeScript app: Next.js 15, React 19, Prisma, Vitest.

## Decision

### 1. Distribution: a Claude Code plugin, served from its own marketplace repo

area54 packages as a **Claude Code plugin**. Target repos install it by name;
updates arrive by version bump rather than by copy-paste. The plugin carries the
agents, the slash commands, the hooks, and the policy files as one versioned
unit.

This is the native mechanism for exactly this problem, and it is the only option
considered that survives the question *"how do you fix a bug in the Lead's
prompt across six repos?"*

Target repos keep their own `CLAUDE.md` — stack, conventions, and Definition of
Done are properties of the product, not of the team. area54 ships the roles;
the repo supplies the context.

### 2. Tooling language: Python 3.12

Supporting tools — frontmatter validators, the policy linter, the eval runner,
the installer — are Python 3.12, managed with `uv`, checked with `ruff` and
`mypy --strict`, tested with `pytest`.

Rationale: this is a proven house language for a sibling Python service, where
the discipline already holds — prior art, not a deployment relationship — the work
is text processing and subprocess orchestration where Python is strongest, and
none of this tooling ever ships to an end user's machine — it runs in CI and in
the maintainer's shell, so runtime distribution is not a constraint.

### 3. Testing: deterministic checks first, evals second

Two layers, in strict priority order:

**Deterministic checks (`pytest`)** — everything that can be decided by reading
files, and therefore must never be left to a prompt:
- every agent has valid frontmatter, a `description`, and an explicit `tools` list
- **no agent holds both review and write authority** — the invariant the Lead
  role depends on
- every command references an agent that exists
- no agent grants a tool its role does not need

**Eval suites (`claude plugin eval`)** — behavioural regression against fixture
repositories with planted defects. Does the Lead catch the injected off-by-one?
Does the PO produce falsifiable criteria from a vague roadmap line? Does the
Tester refuse to weaken a failing test?

Evals are stochastic and are scored against a pass threshold over repeated runs,
never a single trial.

### 4. Everything else

| | |
|---|---|
| Runtime | none — no server, no database, no hosting |
| CI | GitHub Actions, already in place |
| Agent artefacts | Markdown with YAML frontmatter |
| Manifest | JSON |
| Versioning | SemVer; a prompt change that alters agent behaviour is a minor bump, never a patch |

## Data model

None. area54 stores no data. The only persistent state is the target repo's git
history, which is deliberate: per `CLAUDE.md`, GitHub is the team's memory.

## Interfaces

The surfaces area54 exposes to a target repo:

| Surface | Contract |
|---|---|
| `/groom /design /build /review /ship /status` | The CPO's command surface |
| 8 subagents | Invoked by the commands; each with a scoped tool allowlist |
| `.github/workflows/ci.yml` | Reference CI the target repo adapts |
| `.github/pull_request_template.md` | Forces spec link and test evidence |
| `CLAUDE.md` | **Supplied by the target repo**, not by area54 |

## Dependencies

| Dependency | Why | Rejected alternative |
|---|---|---|
| `uv` | Fast, lockfile-based, one tool for envs and deps | `pip` + `venv` — slower, no lockfile by default |
| `ruff` | Lint and format in one, already used in a sibling project | `flake8` + `black` — two tools, slower |
| `mypy --strict` | A sibling project proved the discipline holds | `pyright` — fine, but breaks house consistency |
| `pytest` | House standard | `unittest` — more ceremony, less power |
| `PyYAML` | Parse agent frontmatter | Hand-rolled parser — a bug factory |

No web framework, no ORM, no database driver, no frontend toolchain. If a future
ADR proposes any of these, it should first explain what changed.

## Migration and rollout

Nothing to migrate — greenfield.

1. Convert the current `.claude/` tree into plugin layout with a manifest.
2. Add the deterministic validators and wire them into CI, replacing the
   stack-detection placeholder in `ci.yml`.
3. Install into **one** target repo first, named by the CPO. Prefer a repo that
   is real and active and already has a working test suite, so the team's output
   is judged against standards that exist rather than standards it sets itself.
4. Only after a full feature ships through it end to end, roll to a second repo.

Rollback at any point is uninstalling the plugin. Target repos are unmodified by
installation, which is a property worth protecting in every future decision.

## Risks

**Prompt regression is not deterministically testable.** The most serious risk
here. A wording change can degrade an agent with every file-level check still
green. Mitigated by pushing every mechanical rule into hooks, CI, and branch
protection rather than prose, and by treating evals as a threshold over repeated
runs. Not eliminated. Accepted knowingly.

**Model drift changes behaviour with no repo change.** Agents currently declare
`model: opus`, which floats to whatever "opus" resolves to. A model upgrade can
alter every agent overnight. Mitigation: pin exact model IDs (`claude-opus-5`)
in agent frontmatter and treat a pin change as a minor version bump with a full
eval run. **Not yet done — this is the first follow-up.**

**The plugin API is young.** Packaging format and `claude plugin eval` may move
under us, and eval tooling may require early-access enablement. Mitigated by the
plugin being mostly markdown: a format change is a repackaging job, not a
rewrite. **DevOps must confirm `claude plugin eval` is available on this account
before CI depends on it.**

**Two ecosystems.** Python tooling maintaining a Node-ecosystem artefact. Real,
and accepted: the tooling is CI-side and never crosses into the plugin itself.

**Portfolio inconsistency.** area54 will not match a sibling TypeScript project's
line. Also accepted — that project is the outlier; Python is the house standard.

## Alternatives considered

**Template repository.** Copy `.claude/` into each product repo. Rejected: six
copies drift within weeks, and a fix to the Lead's prompt becomes six PRs.

**Git submodule.** Rejected: `.claude/` must merge with repo-local config rather
than replace it, submodules cannot do partial trees, and every developer pays
the submodule tax forever.

**TypeScript / Node for tooling.** The strongest rejected option — it matches
Claude Code's own ecosystem and `npx` distribution is frictionless. Lost on two
counts: a sibling project has the proven `mypy --strict` discipline and this team
already operates it, and the tooling never leaves CI, so distribution ergonomics buy
nothing here. Revisit if the installer ever needs to run on machines without
Python.

**Go, single static binary** (a single-static-binary approach). Genuinely
attractive for a zero-dependency installer. Rejected as premature: there is no
installer to distribute yet, since the plugin mechanism handles installation.
Reconsider if area54 ever ships a CLI to external users.

**A hosted orchestration service** — a web app that runs the team server-side.
Rejected as a solution to a problem nobody has. It would add a server, a
database, auth, and hosting to a product that currently needs none of them.
