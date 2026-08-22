---
description: CPO dashboard — what is in flight and what needs your decision
allowed-tools: Read, Glob, Grep, Bash
---

Give the CPO a status board. Gather:

- Open PRs and their CI state: `gh pr list --json number,title,isDraft,statusCheckRollup`
- Open issues by label: `gh issue list --label spec --state open`
- Specs in `docs/specs/` and their Status line
- Which specs have an ADR, a design, a branch, a PR — and which do not

Report as one table, ordered by how close each item is to shipping:

| TF | Feature | Stage | Blocked on | Needs CPO? |
|----|---------|-------|-----------|------------|

Stage is one of: Draft spec, Awaiting approval, Designing, Building, In review,
Ready to ship, Shipped.

Then, separately and at the top, list **everything waiting on the CPO** — specs
with open questions, PRs awaiting approval, decisions the team escalated. That
list is the point of this command; put it first.

Be brief. No commentary, no encouragement. Just the board.
