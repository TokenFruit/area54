---
description: Run a roadmap item through the whole team, stopping only at the two CPO gates
argument-hint: <roadmap item, or TF-NNN to resume>
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

Deliver **$ARGUMENTS**.

This is the whole pipeline in one command. You are the conductor: you do not
write specs, code, reviews or tests yourself. Every stage is a subagent, and
your job is to move the artifact to the next one and to stop at the two gates.

**Stop for the CPO exactly twice. Never anywhere else.**

## Gate 1 — the spec

1. Read `docs/roadmap.md` (or `roadmap.md`) for the item and its context.
2. Delegate to the **product-owner** subagent.
3. If the spec has open questions, **stop and put them to the CPO**. Open
   questions are the gate; do not answer them yourself and do not proceed with
   an assumption.
4. If it has none, still stop and report the spec for approval. This gate is
   cheap; catching wrong scope after it is built is not.

Record the CPO's answers **in the spec**, marked `RESOLVED by the CPO`, before
moving on. A decision that lives only in chat is lost by the next session.

## Then run to completion without asking

Once the spec is approved, do not stop again until the merge gate — not for
findings, not for defects, not for a failing test. Those are the team's work,
not the CPO's.

**Design.** Run the **architect** subagent and the **designer** subagent in
parallel, in one message with two tool calls. Skip the designer when the item
has no rendered surface, and say in your report that you did and why. If the
ADR and the design contradict each other, hand both back to the **architect**
subagent to resolve — that is an architecture decision, not a CPO one.

**Build.** Create the branch. Delegate to the **builder-backend** subagent, the
**builder-frontend** subagent, or both in parallel when they touch disjoint
files. Backend first when they would collide.

**Verify.** Run the project's own gates yourself and paste the real output. Do
not take a builder's word for it. If they fail, hand them straight back to the
builder that wrote the code.

**Review.** Run the **lead** subagent and the **tester** subagent in parallel,
in fresh contexts. They must not see each other's output.

**Work the defect loop until it is clean:**

```
lead findings + tester DEFECTs
  → builder fixes            (never the lead, never the tester)
  → lead reviews the fix
  → tester re-verifies
  → repeat
```

Route each finding to the builder that owns the code. Do not fix anything
yourself, and do not let the lead or the tester fix it — the value of a verdict
comes entirely from the person giving it not being the person who wrote the
code.

**Loop until there are no unresolved blockers or majors and the tester passes,
or until two consecutive rounds make no progress.** No progress twice means the
team is stuck: that is worth interrupting the CPO for, and it is the only
unplanned stop permitted.

## Gate 2 — the merge

Open the PR, confirm CI is green, and report to the CPO:

- the spec, the ADR, the branch and the PR
- lead verdict and counts by severity; tester verdict and coverage as `n/m`
- every defect raised, and how it was resolved
- how many rounds the loop took
- CI status, checked from the run and not the badge
- anything the team decided that the CPO would want to have decided

Then stop. **Never merge.** `/ship` is a separate command and merging is the
CPO's.

## Reporting as you go

Say which stage is starting and which agent has it, in one line each. The CPO
is not approving these — they are watching a pipeline run, and silence for
twenty minutes is indistinguishable from a hang.
