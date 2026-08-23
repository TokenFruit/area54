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

If there are blockers, majors, or Tester defects, run the defect loop:

```
Builder fixes  →  Lead reviews the fix  →  Tester re-verifies  →  Tester closes
```

Hand each one to the **builder-backend** subagent or the **builder-frontend**
subagent, whichever owns the code. When the fix lands, re-run this command so
the Lead reviews it and the Tester re-verifies.

Do not fix anything yourself, and do not let the Tester fix it either. The fix
goes through a Builder or the loop is pointless — the value of a verdict comes
entirely from the person giving it not being the person who wrote the code.
