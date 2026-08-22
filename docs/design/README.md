# Design

One directory per feature: `TF-NNN/`, written by the **designer** agent.

- `flows.md` — the journey, per user story
- `states.md` — every UI state; the file Builders work from
- `components.md` — what to reuse, what to create
- `copy.md` — every string the user reads

A design that specifies only the populated state is incomplete. The Lead
rejects PRs that ship a happy path alone.
