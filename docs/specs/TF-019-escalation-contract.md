# TF-019: The escalation contract

**Status:** Draft
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
should reach zero except for the two gates and the named exceptions.

Neither signal is instrumented today. `tools/telemetry.py` records pipeline
events, not messages, so **both are judged by hand until something measures
them** — that is a finding, and it is why acceptance rests on eval coverage
rather than on a metric.

## User stories

- As the CPO, I want the team to reach me only at the two gates and for the
  named exceptions, so that approving work is my whole job in the pipeline.
- As the CPO, I want each message that does reach me to state the outcome and the
  decision I must make, so that I never have to decode an agent's internal
  vocabulary to find out what is being asked.
- As a Builder mid-pipeline, I want a closed list of what escalates, so that I
  do not stall waiting for permission I already have.
- As the maintainer of area52, I want a constitution change to arrive with its
  redeployment consequences stated, so that my repo does not silently diverge.

## Acceptance criteria

1. **Given** `team/TEAM.md`, **when** its `## Escalation` section is read,
   **then** it contains a closed list of what reaches the CPO immediately with at
   least five entries, and a closed list of what must never be surfaced with at
   least five entries, each list stated as a list and marked as exhaustive.
2. **Given** that section, **when** its escalate-immediately list is read,
   **then** it covers at minimum: reaching a CPO gate (with the full PR URL at
   Gate 2); a finding that changes what should be built; a real blocker after the
   role's own stop conditions are exhausted; anything destructive or irreversible,
   including a refused merge gate; and a credential or access the team cannot
   obtain.
3. **Given** that section, **when** its never-surface list is read, **then** it
   covers at minimum: retries and self-corrected failures; routine progress;
   internal mechanics; findings and defects inside an open defect loop; and
   out-of-scope ideas, which go to the PR body's Follow-ups list.
4. **Given** that section, **when** its reporting rule is read, **then** it
   requires a CPO-facing message to state the outcome and the decision, forbids
   relaying raw tool output or status lines into a CPO-facing message, and gives
   at least four concrete translations from an internal term to the CPO's noun.
5. **Given** that section, **when** it is checked against the `## How the work
   flows` section, **then** it names exactly two gates and adds no third, and its
   exceptions are the ones already stated there — stuck twice in the defect loop,
   and a refused merge gate.
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
9. **Given** `python tools/validate.py`, **when** it is run against a
   `team/TEAM.md` whose `## Escalation` section has fewer entries in either
   closed list than criteria 1 requires, **then** it fails and names which list
   is short.
10. **Given** `evals/cases/`, **when** the suite is listed, **then** at least one
    case exercises an agent that hits a mid-pipeline condition on the
    never-surface list and scores it on resolving it and continuing rather than
    addressing the CPO, and at least one scores a CPO-facing message on naming an
    outcome and a decision without internal vocabulary.
11. **Given** those new cases, **when** `python -m tools.evals --list` is run,
    **then** they appear with the same schema as existing cases and a rationale
    stating the failure each looks for.
12. **Given** the repo after this change, **when** `python -m tools.deploy
    <target> --check` is run against any repo the team is deployed into, **then**
    it reports `team/TEAM.md` as stale, so the divergence is visible rather than
    silent.
13. **Given** lint, typecheck, and `pytest`, **when** they run in CI, **then**
    they pass, and any new validator check has a unit test covering both its
    passing and failing case.

## Out of scope

- **Changing the two-gate model.** This item documents the existing gates; it
  does not add, remove, or move one.
- **Redeploying to area52 or any other target repo.** Criterion 12 requires only
  that `--check` reports the staleness. See open question 2.
- **Telemetry on escalations.** Counting interruptions per run is a real want and
  belongs with the cost and cycle-time item in the roadmap's Later.
- **Learning the contract from transcripts.** That is TF-020.
- **A per-agent persona or tone rewrite.** Only escalation language changes.
- **Eval coverage for the five uncovered roles.** That is TF-016; this item adds
  only the cases criterion 10 requires.
- **Any mechanical check on the wording of a message an agent sends at runtime.**
  Nothing in `tools/` sees a CPO-facing message, so this cannot be written.

## Open questions

1. **Does this change the two-gate model?** It should not — criterion 5 asserts it
   does not. Confirm that the only mid-pipeline interruptions remain: stuck twice
   in the defect loop, and a refused merge gate. If you want a third, name it now.
2. **Are target repos redeployed as part of this item, or separately?** This spec
   assumes separately, and only requires that `--check` surfaces the staleness.
   area52 runs on the old constitution until someone redeploys it.
3. **Does the contract bind a direct single-agent invocation, or only `/deliver`?**
   When you invoke `/groom` yourself, you are present in the session, and "never
   surface routine progress" reads oddly. This spec assumes the contract governs
   what is escalated *unprompted*, and that answering a question you asked
   directly is never an escalation. Confirm.
4. **Should `tools/validate.py` check `team/TEAM.md`'s structure at all?**
   Criteria 8 and 9 say yes, and it is the only mechanically checkable part of
   this item. The cost is that you can no longer freely restructure that section
   without touching the validator.
5. **Do the Lead and the Tester get stop-conditions sections?** They are the two
   agents without one. Criterion 7 requires all eight to have one; say if you
   would rather they stay as they are.

## Dependencies

- None blocking. `tools/validate.py`, `tools/deploy.py`, and `evals/` all exist.
- Related, not required: TF-016 (evals for uncovered roles) and TF-020 (learn
  from transcripts) both extend this contract's verification later.
