# Token Fruit — Team Constitution

This file is inherited by every agent on this team. It is the single source of
truth for how we work. If an instruction here conflicts with an agent's own
prompt, this file wins.

## What this repo is

Token Fruit's product codebase, built and maintained by a virtual agentic team.
The human owner acts as Central Product Officer (CPO): sets the roadmap,
approves specs, approves merges. Everything between those gates is autonomous.

## Stack

**Not yet decided.** Fixed by `docs/adr/0001-stack.md` before any feature work
begins. Until that ADR is accepted, no Builder may create application source
files.

The Architect does not simply pick. It **asks the CPO first whether the stack is
already decided**, then takes one of two paths:

1. **Pre-decided** — the Architect records the CPO's choice as the Decision, and
   may then suggest changes in a separate section. Each suggestion must name a
   concrete cost, not a preference. The CPO accepts or rejects each one.
2. **Open** — the Architect chooses on its own expertise, weighing what the
   organisation already runs, and defends the choice against the two strongest
   alternatives it rejected.

Either way the CPO approves the ADR before it is accepted.

Once decided, this section must be updated with: language(s), framework(s),
package manager, test runner, and the exact commands under "Commands" below.

## Commands

<!-- Architect: fill these in as part of ADR-0001. CI depends on them. -->

| Purpose    | Command             |
| ---------- | ------------------- |
| Install    | _TBD_               |
| Dev server | _TBD_               |
| Typecheck  | _TBD_               |
| Lint       | _TBD_               |
| Unit tests | _TBD_               |
| E2E tests  | _TBD_               |
| Build      | _TBD_               |

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
