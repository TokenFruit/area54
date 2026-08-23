---
description: Merge, tag, and deploy an approved and green PR
argument-hint: <PR number>
allowed-tools: Task, Read, Bash
---

Ship PR **$ARGUMENTS**.

Delegate to the **devops** subagent. It must verify the full pre-merge gate
before touching anything:

1. CI green on the latest commit — check the run, not the badge.
2. Lead verdict posted, no unresolved blocker or major.
3. Tester verdict Pass, all acceptance criteria covered.
4. **The merge gate passes.** Its result is the merge decision: a pass merges, a
   refusal goes to the CPO. No separate approval on the PR is required.
5. PR body links the spec; branch is current with `main`.

If any gate fails, stop and report which one. Do not merge.

On success: squash-merge, delete the branch, tag the release, deploy to
**staging** and verify the feature actually works there.

**Stop before production.** Production deploy needs a separate, explicit
instruction from the CPO.

Report: what merged, the version tag, staging status, and the exact rollback
command.
