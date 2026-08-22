---
description: Implement an approved, designed feature on a branch and open a draft PR
argument-hint: TF-NNN
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

Build **$ARGUMENTS**.

Before delegating, verify all of the following and stop if any is missing:
- `docs/specs/TF-NNN-*.md` exists and is approved.
- The ADR for it exists in `docs/adr/`.
- `docs/adr/0001-stack.md` exists. Without it, no code may be written.
- The design directory `docs/design/TF-NNN/` exists, if the feature has UI.

Then:

1. Create branch `tf-<issue>-<slug>` from an up-to-date `main`.
2. Decide the split. If the feature has both server and client work, run
   **builder-backend** and **builder-frontend** in parallel — but only if they
   touch disjoint files. If they would collide, run the backend first so the
   frontend builds against a real interface.
3. Each builder reads `CLAUDE.md`, the spec, the ADR, and the design before
   writing anything.
4. When they return, run typecheck, lint, and the test suite yourself and paste
   the real output. Do not take a builder's word for it.
5. Open a **draft** PR linking the spec and the ADR.

Report: branch, PR URL, criteria covered, criteria not covered and why, and the
verbatim test output.
