---
description: Produce architecture and design for an approved spec
argument-hint: TF-NNN
allowed-tools: Task, Read, Write, Glob, Grep, Bash
---

Produce the technical architecture and the design for **$ARGUMENTS**.

First, verify the spec is approved — its Status must not be `Draft`, and it
must have no unanswered open questions. If it does, stop and tell the CPO
which questions are outstanding.

Then run both of these **in parallel**, in a single message with two tool calls,
since neither depends on the other:

- The **architect** subagent, to write the ADR from the spec.
- The **designer** subagent, to write the design directory from the spec.

If `docs/adr/0001-stack.md` does not exist, run the architect **alone** first to
produce it — the stack decision blocks everything, including the design.

When both return, cross-check their outputs and report any contradiction to the
CPO: an interface the design needs that the ADR does not provide, or a state the
ADR cannot support. Do not resolve contradictions yourself.

Report: the ADR path, the design directory, the key decisions, and any conflict
you found.
