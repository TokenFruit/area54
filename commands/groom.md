---
description: Turn a roadmap item into an approved-ready feature spec
argument-hint: <roadmap item, TF number, or description>
allowed-tools: Task, Read, Write, Glob, Grep, Bash
---

Groom this into a buildable spec: **$ARGUMENTS**

1. Read `docs/roadmap.md` for the item and its surrounding context.
2. Check `docs/specs/` for the next free TF number and for any spec this
   might conflict with.
3. Delegate to the **product-owner** subagent. Give it the roadmap item
   verbatim, the TF number to use, and any extra context the CPO just supplied.
4. When it returns, create a GitHub issue for the spec:
   `gh issue create --title "TF-NNN: <name>" --body-file <spec path> --label spec`
5. Report to the CPO: the spec path, the issue URL, the scope decisions the PO
   made, and **every open question** — these block approval.

Do not proceed to design or build. This command ends at CPO approval.
