---
description: Run Lead review and Tester validation against an open PR
argument-hint: <PR number>
allowed-tools: Task, Read, Glob, Grep, Bash
---

Review PR **$ARGUMENTS**.

Run these two **in parallel**, in one message with two tool calls. They must not
see each other's output — independence is the entire point of running both.

- The **lead** subagent: review the diff against the spec and `CLAUDE.md`,
  post findings to the PR, return a verdict.
- The **tester** subagent: write acceptance tests from the spec, run the full
  suite, run regressions, post the plan and results, return a verdict.

Then check CI: `gh pr checks $ARGUMENTS`.

Report to the CPO a single consolidated verdict:

- Lead: verdict, and the count at each severity.
- Tester: verdict, and coverage as `n/m` criteria.
- CI: pass or fail, with the failing job named.
- **Ready to ship: yes / no.** Yes requires all three: no unresolved blocker or
  major, Tester pass with full coverage, and green CI.

If there are blockers or majors, hand them back to the relevant builder to fix,
then re-run this command. Do not fix them yourself — the fix must go through the
builder so the review loop stays honest.
