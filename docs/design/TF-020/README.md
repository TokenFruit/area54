# TF-020 — design

**Judgement: this feature has a design surface, and it is a terminal.**

On TF-019 the Designer wrote nothing, correctly: that deliverable was prose in
`team/TEAM.md`, and a `copy.md` would have been a second normative copy of it.

TF-020 differs in one decisive way. Criterion 11 puts a human at a decision
point — the CPO accepting or rejecting each proposed edit, one at a time, with a
diff and verbatim evidence in front of him — and refuses to run at all without
an attached terminal. Resolved question 5 makes what he *sees* at that moment
deliberately different from what is *stored*. The spec's own verification table
marks 11 and 13 as human-observable, "a read" of whether the surface makes the
decision easy. That is a design surface with a designer-shaped question in it:
what must the CPO see to accept or reject responsibly, and in what order.

There are also real non-populated states with nothing obvious about them — no
evidence found, nothing new since the last run, a ceiling breached mid-run, a
transcript that could not be redacted, a proposal whose staging diff disagrees
with itself. Left unspecified, eight of them get invented inside the code.

## What is here, and what is not

| File | Status |
| ---- | ------ |
| `flows.md` | Applies. Two commands, one review loop, every branch. |
| `states.md` | Applies, and is the file the Builder works from. |
| `copy.md` | Applies. Every string the CPO reads. |
| `components.md` | **Applies only in a reduced form.** See below. |

**`components.md` in its usual sense does not apply.** area54 has no client, no
rendered surface and no component library; there is nothing to mark `[existing]`
or `[new]` in the UI sense, and no props or variants exist to specify. What the
file records instead is the small set of **render and input primitives** the
Builder will otherwise reinvent per call site — the report-line format inherited
from `tools/telemetry.py`, the `[PASS]`/`[FAIL]` column from
`tools/merge_gate.py`, the `::error::` prefix, and the one genuinely new thing:
the per-edit review card and its keypress contract. It is an inventory of
conventions, not of components, and it is labelled as such.

No visual mockup is published. The layouts here are ~80 columns of monospaced
text; prose renders them exactly, and an HTML artifact would render them less
faithfully than the code block already does.

## Not decided here

The CLI verbs, flags and state-directory layout are named throughout so the
flows are legible. **The ADR owns them.** Where ADR-0003 lands on a different
name, the ADR wins and this design's structure survives the rename unchanged.
