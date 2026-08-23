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
   **Then** it also states, in those words, that the contract governs
   **unprompted** escalation only, and that answering a question the CPO asked
   directly is never an escalation and is not bound by the two closed lists.
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
14. **Given** `.claude/agents/devops.md` and `.claude/commands/ship.md`, **when**
    each is read, **then** neither states CPO approval as a precondition for
    running the merge gate, and both state that the gate's result is the merge
    decision: a pass merges, and a refusal goes to the CPO.
15. **Given** `team/TEAM.md`, `.claude/agents/devops.md` and
    `.claude/commands/ship.md`, **when** the three are read together, **then**
    they agree on what authorises a merge, and none of them names a precondition
    the other two omit.

### Why 14 and 15 are in this item

Added by the CPO after approval. `tools/merge_gate.py` was built to replace CPO
approval at Gate 2, and the CPO ruled for it — but the instructions it replaced
were never removed. `devops.md` still says "you run only after the CPO has
approved the PR. No amount of green changes that", `ship.md` still calls explicit
CPO approval "absolute", and `TEAM.md` lists six rules with approval among none
of them. Three documents, two answers, so devops waits for the CPO on a PR the
gate would have merged.

That is an escalation defect, which is why it lands here rather than in its own
item: it interrupts the CPO for a decision the gate already makes. It is the same
failure this spec exists to fix, expressed in configuration instead of in prose.

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

## Resolved questions

All five are answered. Nothing blocks the build.

1. **Does this change the two-gate model?** **No.** Ruled by the CPO: no third
   gate. Criterion 5 stands as written — exactly two gates, and the only
   mid-pipeline interruptions remain stuck twice in the defect loop and a refused
   merge gate. An agent that wants to interrupt for anything else is wrong.
2. **Are target repos redeployed as part of this item, or separately?**
   **Separately.** Ruled by the CPO. Criterion 12 stands: `--check` must report
   `team/TEAM.md` as stale, so the divergence is visible. area52 keeps running the
   old constitution until a separate redeployment lands, and that redeployment
   needs its own roadmap line or it will be forgotten.
3. **Does the contract bind a direct single-agent invocation, or only
   `/deliver`?** **It governs unprompted escalation only.** Answering a question
   the CPO asked directly is never an escalation, and the two closed lists do not
   apply to it. The `TEAM.md` wording must say **unprompted** explicitly — without
   that word an agent will over-apply the never-surface list and go silent when it
   was asked a direct question, which is a worse failure than the one this item
   fixes. Criterion 4 now requires it.
4. **Should `tools/validate.py` check `team/TEAM.md`'s structure?** **Yes.**
   Every unenforced rule in this repo has decayed; a contract nothing checks would
   be the fourth instance. The cost is accepted, and bounded by how criteria 8 and
   9 are already written: the check asserts the **presence and minimum length of
   the two closed lists**, never exact headings or wording, so the section can
   still be restructured without touching the validator. A check that pins prose
   is out of scope and must not be written.
5. **Do the Lead and the Tester get stop-conditions sections?** **Yes**, per
   criterion 7. They are the two roles most able to loop forever — the Lead can
   review indefinitely, and the Tester drives the defect loop. Today the "stuck
   twice" bound lives only in `TEAM.md`; giving both agents a stop-conditions
   section puts the bound in the file of the agent that has to obey it.

Answers 1 and 2 are the CPO's. Answers 3, 4 and 5 were delegated to the
assistant by the CPO and adopted as written; any of the three can be reversed on
a word, which would reopen the criteria they name.

## Dependencies

- None blocking. `tools/validate.py`, `tools/deploy.py`, and `evals/` all exist.
- Related, not required: TF-016 (evals for uncovered roles) and TF-020 (learn
  from transcripts) both extend this contract's verification later.
