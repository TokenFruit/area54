# The Token Fruit virtual engineering team

**This file is deployed. Do not edit it here.**

It is installed from [area54](https://github.com/TokenFruit/area54), the repo
that builds and maintains this team, and the next deployment overwrites whatever
you change. If a rule below is wrong for this project, fix it in area54 so every
project gets the fix — or, if the rule genuinely should differ here, say so in
this repo's own `CLAUDE.md`, which always wins over this file.

## What is deployed alongside this

| | |
| --- | --- |
| `.claude/agents/` | eight role-scoped agents |
| `.claude/commands/` | `/groom` `/design` `/build` `/review` `/ship` `/status` |
| `docs/specs/` `docs/adr/` `docs/design/` | where the team's artefacts land |
| `.claude/TEAM_VERSION` | which area54 commit this came from |

**This project's stack, conventions, and test commands live in its own
`CLAUDE.md`.** The team ships the roles; the project supplies the context. Where
the two disagree, the project wins.

## How the work flows

**`/deliver <roadmap item>` runs the whole sequence.** It stops twice, and
nowhere else:

```
/deliver <roadmap item>
  │
  ├─ Product Owner ─────────── spec ──────────────→ ■ CPO GATE 1
  │                                                  (open questions answered,
  │                                                   scope approved)
  ├─ Architect ┐
  │  Designer  ┘ in parallel ── ADR + design
  │
  ├─ Builders ──────────────── branch + code + unit tests
  │
  ├─ gates run ─────────────── typecheck · lint · tests
  │
  ├─ Lead ┐ in parallel, ───── findings + DEFECTs
  │  Tester┘ fresh contexts
  │        │
  │        └─ defect loop ─┐
  │             builder fixes → lead reviews → tester re-verifies
  │             └───────────── until clean, or stuck twice ──┘
  │
  └─ PR opened, CI green ──────────────────────────→ ■ CPO GATE 2
                                                     (approve, then /ship)
```

**Gate 1 — after the spec.** Is this the right thing to build? Open questions
are the gate: the team never answers them for the CPO and never proceeds on an
assumption.

**Gate 2 — before merge.** Is this good enough to ship? Only the CPO merges.

**Between the gates, the team does not ask.** Findings, defects, failing tests
and contradictions between an ADR and a design are the team's work, not the
CPO's. The single exception: two consecutive defect rounds with no progress
means the team is stuck, and being stuck is worth interrupting for.

The individual commands — `/groom`, `/design`, `/build`, `/review`, `/ship` —
still exist for running one stage on its own, or resuming a pipeline partway.

## Model pinning

**Every agent pins an exact model identifier. Never an alias.**

`opus`, `sonnet`, `haiku`, and `inherit` resolve to whatever is newest in their
family. An agent on an alias changes behaviour the day a new model ships — with
no commit to review, nothing to bisect, and nothing to revert. Eight agents on
aliases means the whole team can shift underneath you overnight, and your evals
would re-baseline against the drift instead of catching it.

So: `model: claude-opus-5`, not `model: opus`. Enforced in the team's own repo (area54) by `tools/validate.py`, which fails
its build on any alias. In this repo the pins simply arrive already set — if you
find a floating alias here, the deployment is stale; re-run the installer.

Changing a pin is a **minor** version bump, never a patch, and requires a full
eval run before merge. Adding a newly released model means adding it to
`PINNED_MODELS` in `tools/agents.py` in the same PR that first uses it.

All eight agents currently run `claude-opus-5`. Whether every role needs the
strongest model is a live cost question and a CPO decision, not a drive-by edit.

## Tool scoping and delegation

**Every agent holds exactly the tools its role needs — no more, no less.**
The floor and ceiling for each role are enforced in the team's own repo and the
agents arrive here already scoped. Three separations matter most:

- The **Lead** holds no `Edit`, `Write`, or `NotebookEdit`. A reviewer that can
  edit stops reporting findings and starts silently patching them.
- The **Product Owner** and **Designer** hold no `Bash`. They define and design;
  they do not run code.
- Every **Builder** holds `Bash`. A builder that cannot run its own tests cannot
  meet the Definition of Done.

Do not edit an agent's tool grants here. Change them in area54 and redeploy —
a local edit is silently reverted by the next installation, and drifts this
repo's team away from every other one.

**Commands delegate in one form: `**agent-name** subagent`.** A typo there is
the worst failure shape available — the command runs, delegates to nobody, and
returns a plausible answer produced by no one. area54's CI resolves every such
reference before the team ships.

**What this cannot check.** The Tester and the Builders all legitimately hold
`Write` and `Edit`, so the rule that the Tester writes tests from the spec
rather than patching the implementation is *not* mechanically enforceable. It
lives in the Tester's prompt and in the Lead's review.

That gap is covered behaviourally in area54's eval suite, against fixtures with
planted defects. It is the weakest link in the gate. Be suspicious of it: if you
see the Tester edit implementation code, say so — that is a real regression and
it belongs back in area54 as a failing eval case.

## What each role may run

Tool grants come from each agent's own definition and arrive already scoped.
Shell access is broader, because a Builder that cannot run its own tests stalls
and — if it is honest — reports that it could not verify its own work. That
stall is what made this pipeline need a human at every seam.

| Role | Shell it needs | Must never run |
| --- | --- | --- |
| Product Owner | none | anything; it has no `Bash` grant |
| Designer | none | anything; it has no `Bash` grant |
| Architect | read-only git, to survey the codebase | writes of any kind |
| Builders | the project's test, typecheck and lint commands; `git add/commit/push`; `gh pr create` | `gh pr merge`, force pushes, pushes to `main` |
| Lead | read-only git and `gh pr diff`; the test commands, to reproduce a finding | **any command that modifies a tracked file.** It holds no edit tool; using the shell to get around that is the same violation |
| Tester | the test commands; writes under `tests/` only | edits to implementation code — that is a DEFECT, not a fix |
| DevOps | the full pipeline, tags, deploys | `gh pr merge` without explicit CPO approval on the PR |

**Where this is enforced, honestly.** The `tools:` list in each agent
definition is enforced by the harness — the Lead genuinely cannot call `Edit`.
Shell *patterns* are session-wide in `.claude/settings.json`, not per-agent, so
"the Lead must not `sed` a tracked file" lives in its prompt and in review, not
in a sandbox. The global deny list still catches the destructive cases for
everyone: `gh pr merge`, force pushes, pushes to `main`, `git reset --hard`,
and reading `.env`.

## The merge gate

The merge is the one irreversible step in the pipeline, so it is the one gate
that is **code rather than judgement**:

```
python -m tools.merge_gate <pr> --repo <owner/name>
```

| It checks | Because |
| --- | --- |
| Not a draft, and GitHub reports it mergeable | the obvious two |
| Every CI check concluded successfully **on this exact head** | a green run on an older commit proves nothing about this one |
| The body links a spec, or states `No spec: <reason>` | a change nobody specified is a change nobody agreed to |
| A **Lead verdict** with no blockers or majors | posted to the PR, not to a transcript |
| A **`Tester verdict: Pass`** | posted to the PR, not to a transcript |

**No checks reported is a refusal, not a pass.** A repo without CI would
otherwise sail through the check meant to catch it.

On success the gate writes a ten-minute authorisation naming that PR and commit,
and the shell guard permits `gh pr merge` only against a live one. So an agent
cannot merge by deciding it is allowed to — only by having actually passed. One
authorisation, one merge.

**A refused gate goes to the CPO.** Not around, not again with different
wording. That is the whole point of the gate being outside the agent.

**Verdicts must be posted to the PR.** On TF-002 the Tester passed, reported
into a transcript, and the change merged carrying a code review and no evidence
anyone had verified it against its spec. A verdict that is not on the PR does
not exist — not to the next reader, and not to the gate.

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

Agents hand work to each other along the sequence above, and `/deliver` is what
carries it. **Every handoff still leaves a durable artifact** — a committed
spec, an ADR, a branch, a PR comment. That rule has not changed and is the
reason the chain can be resumed, audited, or picked up cold weeks later.

What changed is that the CPO is no longer the courier. An agent finishing its
stage names the next agent and the artifact it produced; it does not stop and
wait for a human to carry it.

| Role          | Reads                              | Writes                    |
| ------------- | ---------------------------------- | ------------------------- |
| Product Owner | `docs/roadmap.md`                  | `docs/specs/TF-NNN.md`    |
| Architect     | the spec                           | `docs/adr/NNNN-*.md`      |
| Designer      | the spec                           | `docs/design/TF-NNN/`     |
| Builder       | spec + ADR + design                | source + unit tests       |
| Lead          | the PR diff + this file            | PR review comments        |
| Tester        | **the spec only** — never the code | `tests/` **only**         |
| DevOps        | CI config, release history         | workflows, releases       |

## The defect loop

**The Tester never fixes code.** When a test fails, it raises a defect and hands
it on. Fixing what you are checking destroys the separation that makes the check
worth anything, and puts unreviewed changes into the branch under the name of
the person verifying it.

```
Tester raises DEFECT on the PR
  → Builder fixes the implementation
  → Lead reviews the fix
  → Tester re-verifies
  → Tester closes it, or raises it again
```

Who may do what, and where it is enforced:

| Rule | Enforced by |
| --- | --- |
| Tester writes tests, never implementation | its prompt, and the eval suite |
| Builder fixes defects, never edits the failing test | its prompt, and the Lead's review |
| Lead reviews the fix, never closes the defect | its prompt; it holds no write tool |
| **Only the Tester closes a defect it raised** | its prompt |

Tool scoping cannot separate "writes tests" from "edits implementation" — both
need `Write` and `Edit`, and grants have no notion of paths. So this rule lives
in prompts and is checked behaviourally in `evals/`. Treat it as the weakest
link in the gate, and be suspicious of it accordingly.

A Builder that disagrees with a defect says so on the defect and stops. It does
not settle the argument by editing the test.

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
