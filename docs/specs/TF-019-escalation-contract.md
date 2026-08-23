# TF-019: The escalation contract

**Status:** Approved — CPO, 2026-08-23
**Roadmap item:** "TF-019 — The escalation contract. `TEAM.md` says what an agent does when it is blocked and nothing about what must never reach the CPO, so agents narrate mechanics where they should report an outcome and a decision"
**Author:** Product Owner agent

## Problem

The CPO has two gates and everything between them is meant to be autonomous, but
the team still interrupts him for things that need no decision from him, and when
it does report, it reports mechanics — branch names, hook states, gate labels,
raw command output — rather than the outcome and the decision he actually has to
make. `TEAM.md`'s `## Escalation` is six lines that cover only the blocked case:
it says stop and report, and says nothing about what must *never* be surfaced or
in what language a report is written.

## Outcome

Reading the constitution is enough to answer "does this reach the CPO, and if so
in what words" without asking him. Two signals should move: the proportion of
CPO-facing messages that carry a decision he must make rather than a status
update, and the number of mid-pipeline interruptions per `/deliver` run, which
should reach zero except for the two gates and the escalate-immediately list.

Neither signal is instrumented today. `tools/telemetry.py` records pipeline
events, not messages, so **both are judged by hand until something measures
them** — that is a finding, and it is why acceptance rests on eval coverage
rather than on a metric.

## Gates and escalations are different things

The first review found criteria 2 and 5 mandating and forbidding the same thing:
one word doing two jobs. A **gate** is a stop: the pipeline halts and waits for
the CPO before continuing, and there are exactly two. An **escalation** is a
report that interrupts without halting at a gate, and criterion 2's six
categories are the complete set of them — closed, not a floor. An agent may not
escalate a seventh: that is a constitution change. Criteria 2 and 3 bind the
Builder's prose, which may word a category more fully but may not add or drop
one. ADR-0002's reading, adopted here. `team/TEAM.md:59-62` calls two
stuck defect rounds "**the single exception**", which is now simply wrong — the
CPO has confirmed all six categories interrupt (resolved question 6), so the
stuck loop is one entry among six, not the only one. Criterion 16 is therefore
load-bearing rather than tidying: it removes a false statement.

## User stories

- As the CPO, I want the team to reach me only at the two gates and for the
  escalate-immediately list, so that approving work is my whole job in the
  pipeline.
- As the CPO, I want each message that does reach me to state the outcome and the
  decision I must make, so that I never have to decode an agent's internal
  vocabulary to find out what is being asked.
- As a Builder mid-pipeline, I want a closed list of what escalates, so that I
  do not stall waiting for permission I already have.
- As the maintainer of area52, I want a constitution change to arrive with its
  redeployment consequences stated, so that my repo does not silently diverge.

## Acceptance criteria

1. **Given** `team/TEAM.md`, **when** its `## Escalation` section is read,
   **then** it contains a Markdown list of what reaches the CPO immediately with
   at least five entries, and a Markdown list of what must never be surfaced with
   at least five entries. **And** — read by a human, not by a tool — the section
   says that the two lists are complete, and that a condition on neither list is
   the agent's own to resolve. No mechanical check may assert that wording; see
   resolved question 4.
2. **Given** that section, **when** its escalate-immediately list is read,
   **then** it covers these six categories and no others: reaching a CPO gate
   (with the full PR URL at Gate 2); a finding that changes what should be built;
   an impediment that the role's own stop conditions did not clear; anything
   destructive or irreversible, including a refused merge gate; a credential or
   access the team cannot obtain; and **two consecutive defect rounds with no
   progress**, stated with that count and not as a general "the team is stuck".
   "Impediment", not "blocker" — `blocker` is a Lead severity in this repo
   (`team/TEAM.md:159`, `:185`) and must not be overloaded here.
   **The stuck-loop entry carries a numeric bound the constitution states
   nowhere else in prose** — only at `team/TEAM.md:61`, which criterion 16
   rewrites, and in the flow diagram at `:47` ("until clean, or stuck twice").
   It must appear in this list with its count intact, or criterion 16 deletes
   the loop's only stated end.
3. **Given** that section, **when** its never-surface list is read, **then** it
   covers these five categories and no others: retries and self-corrected
   failures; routine progress; internal mechanics; findings and defects inside an
   open defect loop; and out-of-scope ideas, which go to the PR body's Follow-ups
   list. **And** the defect-loop entry states its own limit in the same sentence:
   findings inside an open loop stay silent *until* the loop hits criterion 2's
   two-round bound, at which point the loop itself escalates.
4. **Given** that section, **when** its reporting rule is read, **then** it
   requires a CPO-facing message to state the outcome and the decision, forbids
   relaying raw tool output or status lines into a CPO-facing message, and gives
   at least four concrete translations from an internal term to the CPO's noun.
   **Then** it also states, in those words, that the contract governs
   **unprompted** escalation only, and that answering a question the CPO asked
   directly is never an escalation and is not bound by the two closed lists.
5. **Given** that section, **when** it is read against `## How the work flows`,
   **then** it names exactly two CPO **gates** and adds no third, it distinguishes
   a gate from an escalation in the terms above, and it names no mid-pipeline
   interruption outside criterion 2's escalate-immediately list.
6. **Given** the rewritten section, **when** it is read against `## The merge
   gate` and the Tester's and Builder's duty to paste verbatim output, **then**
   the ban on relaying raw output is scoped to CPO-facing messages only and
   states that durable artifacts — PR comments, verdicts, specs, ADRs — still
   carry exact evidence.
7. **Given** each of the eight files in `.claude/agents/`, **when** it is read,
   **then** it has a stop-conditions section and a closing line naming what its
   final message must contain, and every escalation trigger it names is an
   instance of a category in criterion 2 rather than a new category.
8. **Given** `python tools/validate.py`, **when** it is run on this repo,
   **then** it fails if any agent definition is missing either section from
   criterion 7, naming the agent and the missing section.
9. **Given** the new `team/TEAM.md` check, **when** it is called as a **function
   taking a path**, in the style of `tools.settings.validate(path=...)`
   (`tools/settings.py:274`), against a `TEAM.md` whose `## Escalation` section
   has fewer entries in either list than criterion 1 requires, **then** it returns
   a failure naming which list is short. `python tools/validate.py` keeps its
   current contract — **no arguments** — and runs that check against this repo's
   own `team/TEAM.md`. A Builder must not add a positional argument to the CLI;
   CI invokes it bare.
10. **Given** `evals/cases/` and `evals/fixtures/`, **when** they are read,
    **then** two new cases exist, each naming a `fixture` that exists on disk —
    none of the three current fixtures presents a mid-pipeline never-surface
    condition, so at least one new fixture is part of this work — and each
    `expect` block is built only from the harness's five primitives
    (`tools/evals/case.py:20-50`). One case puts an agent in front of a
    never-surface condition and `forbids` patterns that address the CPO; the
    other targets a CPO-facing message, `mentions` an outcome-and-decision
    phrasing and `forbids` at least three internal terms from criterion 4's
    translation table. **The criterion is satisfied by the cases existing,
    parsing, and asserting that shape.** The harness has no semantic scorer, so
    whether the regexes are good proxies is a human judgement, and no trial
    outcome is required — no live trial can complete today (`CLAUDE.md`).
11. **Given** those two cases, **when** each YAML file is **read**, **then** each
    has a non-empty `rationale:` naming the failure it looks for. **And when**
    `python -m tools.evals --list` is run, **then** both appear in the listing —
    which demonstrates only that they load and parse. `--list` prints name, agent
    and threshold/trials and nothing else (`tools/evals/__main__.py:56`), so the
    rationale is verified by reading the file, never by that command.
12. **Given** the repo after this change, **when** `python -m tools.deploy
    <target> --check` is run against any repo the team is deployed into, **then**
    it exits non-zero and its plan names **`.claude/TEAM.md`** among the changed
    files. That is the destination path; `PAYLOAD` maps `team/TEAM.md` →
    `.claude/TEAM.md` (`tools/deploy.py:45`) and the plan prints destinations, so
    the source path never appears in that output.
13. **Given** lint, typecheck, and `pytest`, **when** they run in CI, **then**
    they pass, and any new validator check has a unit test covering both its
    passing and failing case.
14. **Given** `.claude/agents/devops.md`, `.claude/commands/ship.md`, and
    `team/TEAM.md`'s "What each role may run" table, **when** each is read,
    **then** none of the three states CPO approval as a precondition for merging
    or for DevOps running at all. Named explicitly, because each is a different
    phrasing: `devops.md`'s "you run only after the CPO has approved the PR" (line
    17) — which also contradicts that same file's lines 59-66, so removing it is
    the fix there; `ship.md`'s pre-merge item 4, "**Explicit CPO approval on the
    PR.** No approval, no merge"; and the DevOps row's "`gh pr merge` without
    explicit CPO approval on the PR" (`team/TEAM.md:135`). **And** all three state
    that the merge gate's result is the merge decision: a pass merges, a refusal
    goes to the CPO.
15. **Given** `team/TEAM.md`, `.claude/agents/devops.md` and
    `.claude/commands/ship.md`, **when** the three are read together, **then**
    they agree on what authorises a merge, and none of them names a precondition
    the other two omit. `team/TEAM.md` must also agree with itself: its
    `## The merge gate` table lists five checks and approval is not among them,
    while its role table at `:135` requires approval.
16. **Given** `team/TEAM.md`'s `## How the work flows`, **when** its "Between the
    gates, the team does not ask" paragraph is read, **then** it no longer calls
    two consecutive defect rounds "the single exception", and instead points at
    `## Escalation`'s escalate-immediately list as the complete set. Nothing in
    that section names an interruption the `## Escalation` list omits. **The
    two-consecutive-rounds bound is not deleted, only moved**: it must be
    present in criterion 2's list before this paragraph stops stating it, and
    the flow diagram's "until clean, or stuck twice" (`team/TEAM.md:47`) stays
    as it is, so the two never disagree.

### How each criterion is verified

Mechanically, by `pytest` or a named command: 1 (list presence and length only),
8, 9, 11 (the `--list` half), 12, 13. By a human reading the files: 1 (the
completeness clause), 2, 3, 5, 6, 11 (the rationale half), 14, 15, 16. Criteria
4, 7 and 10 are mixed — the literal word `unprompted` and the presence of both
sections per agent are mechanical; whether a trigger is an instance of a
category is not. **Criterion 10's mechanical half:** the cases existing,
loading, naming a fixture that resolves on disk — already enforced for every
case by `tests/test_eval_harness.py:46` — and their `expect` blocks using only
the five primitives, which is a `pytest` over the YAML keys. Only proxy quality
is the human read.

**This is stated here on purpose.** `team/TEAM.md`'s Definition of Done item 1
requires every acceptance criterion to have a passing automated test, and this
spec cannot meet that literally: nothing in `tools/` sees a CPO-facing message,
and no tool decides agreement between prose documents. The Tester on the
implementation PR should record that exception against this section rather than
choose between a false Pass and a Fail on a spec the CPO approved.

### Why 14, 15 and 16 are in this item

Added by the CPO after approval. `tools/merge_gate.py` was built to replace CPO
approval at Gate 2, and the CPO ruled for it — but the instructions it replaced
were never removed. `devops.md:17` still says "you run only after the CPO has
approved the PR. No amount of green changes that", `ship.md:15-16` still calls
explicit CPO approval "absolute", and `team/TEAM.md:135` still forbids DevOps
`gh pr merge` "without explicit CPO approval on the PR" — even though the merge
gate's own table in the next section lists five checks, approval among none of
them. **Three files, four sites, and `TEAM.md` and `devops.md` each contradict
themselves.** So devops waits for the CPO on a PR the gate would have merged.

That is an escalation defect — it interrupts the CPO for a decision the gate
already makes — which is why it lands here rather than in its own item: the same
failure this spec exists to fix, expressed in configuration instead of prose.
Criterion 16 belongs with them because a "single exception" that is not the only
exception sends an agent to the CPO for a ruling the contract already makes.

## Out of scope

- **Changing the two-gate model.** This item documents the existing gates; it
  does not add, remove, or move one.
- **Redeploying to area52 or any other target repo.** Criterion 12 requires only
  that `--check` reports the staleness. See resolved question 2.
- **Telemetry on escalations.** Counting interruptions per run is a real want and
  belongs with the cost and cycle-time item in the roadmap's Later.
- **Learning the contract from transcripts.** That is TF-020.
- **A per-agent persona or tone rewrite.** Only escalation language changes.
- **Eval coverage for the five uncovered roles.** That is TF-016; this item adds
  only the two cases and the fixture criterion 10 requires.
- **A semantic scorer for the eval harness.** Criterion 10 is deliberately
  written to the five primitives that exist rather than requiring a sixth.
- **Any mechanical check on the wording of a message an agent sends at runtime.**
  Nothing in `tools/` sees a CPO-facing message, so this cannot be written.

## Resolved questions

1. **Does this change the two-gate model?** **No.** Ruled by the CPO: no third
   gate. Criterion 5 stands — exactly two gates. What the first review forced
   apart is that *gates* and *escalations* are different things: the complete set
   of mid-pipeline interruptions is criterion 2's escalate-immediately list, not
   the two named at `team/TEAM.md:59-62`. Widened by the CPO in question 6.
2. **Are target repos redeployed as part of this item, or separately?**
   **Separately.** Ruled by the CPO. Criterion 12 stands: `--check` must report
   the constitution as stale, so the divergence is visible. area52 keeps running
   the old constitution until a separate redeployment lands, and that
   redeployment needs its own roadmap line or it will be forgotten.
3. **Does the contract bind a direct single-agent invocation, or only
   `/deliver`?** **It governs unprompted escalation only.** Answering a question
   the CPO asked directly is never an escalation, and the two closed lists do not
   apply to it. The `TEAM.md` wording must say **unprompted** explicitly — without
   that word an agent will over-apply the never-surface list and go silent when it
   was asked a direct question, which is a worse failure than the one this item
   fixes. Criterion 4 requires it.
4. **Should `tools/validate.py` check `team/TEAM.md`'s structure?** **Yes.**
   Every unenforced rule in this repo has decayed. The cost is bounded by how
   criteria 1 and 9 are written: the check asserts the **presence and minimum
   length of the two lists**, never exact headings or wording, so the section can
   be restructured without touching the validator. A check that pins prose is out
   of scope and must not be written — which is why criterion 1's completeness
   clause is explicitly a human read.
5. **Do the Lead and the Tester get stop-conditions sections?** **Yes**, per
   criterion 7. They are the two roles most able to loop forever — the Lead can
   review indefinitely, and the Tester drives the defect loop. Both already have a
   closing line (`lead.md:104`, `tester.md:134`) and neither has a stop-conditions
   section, so this is one new section each, in two files.

6. **Is criterion 2's list the complete set of mid-pipeline interruptions, given
   that it widens resolved question 1?** **Yes — all six escalate-immediately
   categories are confirmed**, by the CPO on 2026-08-23. His round-2 ruling
   settled that "a finding that changes what should be built" and "a credential
   the team cannot obtain" **do** interrupt mid-pipeline; criterion 2 carried
   five entries then, and round 3 added "two consecutive defect rounds" to close
   a Lead blocker without updating this answer. Six is a count correction, not a
   fresh authorisation — question 1's ruling already named the stuck loop.
   Criteria 2, 5 and 16 are settled. So `team/TEAM.md:61`'s "the single
   exception" is factually wrong — six escalating conditions, not one — which is
   why criterion 16 is required rather than cosmetic.

Answers 1, 2 and 6 are the CPO's. Answers 3, 4 and 5 were delegated to the
assistant by the CPO and adopted as written; any of the three can be reversed on
a word, which would reopen the criteria they name.

## Dependencies

- None blocking. `tools/validate.py`, `tools/deploy.py`, and `evals/` all exist.
- Related, not required: TF-016 (evals for uncovered roles) and TF-020 (learn
  from transcripts) both extend this contract's verification later.
