# Token Fruit Roadmap

Owned by the CPO. This file is the **only** input to the team. Nothing gets
built that does not start as a line here.

Keep items to one or two lines. Precision is the Product Owner's job — your job
is to say what matters and in what order. If you find yourself writing
acceptance criteria here, stop and run `/groom` instead.

## Now

<!-- What the team is working on or picking up next. Keep this short —
     three or four items. A long "Now" is a "Next" in disguise. -->

- [ ] TF-003 — Package the team as a Claude Code plugin, so a prompt fix reaches
      every product repo by version bump instead of six copy-pastes

## Next

<!-- Committed, not started. -->

- [ ] TF-007 — Run the evals for real. Needs the Claude Code CLI installed and
      credentials available; the harness has never executed a live trial, so
      the cases are a statement of intent, not evidence
- [ ] TF-006 — Deploy to the first target repo. **Blocked: the CPO names the
      target.** Not `area53` — area54 is independent of Gempli. Prefer a repo
      that is real, active, and already has a test suite, so the team's output
      is judged against standards that exist

## Later

<!-- Wanted, not committed. Ideas live here until they earn a promotion. -->

- [ ] Integrate `no-mistakes` as the code-quality gate ahead of PR, with review
      auto-fix off, keeping the Lead and Tester on spec fidelity
- [ ] Per-repo team profiles — not every product needs all seven roles
- [ ] Cost and cycle-time telemetry per feature, so the CPO can see what the
      team costs and where it stalls

## Done

<!-- Shipped. Keep the TF number and the date. -->

- [x] **TF-001** — Decide the technical stack — ADR-0001, 2026-08-23
- [x] **TF-002** — Pin exact model IDs in every agent, and guard the pin in
      CI — 2026-08-23
- [x] **TF-004** — Tool scoping per role, and every command delegation resolved
      against a real agent — 2026-08-23
- [x] **TF-005** — Eval harness: fixtures with planted defects, scoring over
      repeated trials, four cases. Not yet run live — 2026-08-23

---

### How an item moves

```
roadmap line
  → /groom TF-NNN   Product Owner writes the spec       → CPO APPROVES
  → /design TF-NNN  Architect + Designer, in parallel
  → /build TF-NNN   Builders implement, open draft PR
  → /review <PR>    Lead + Tester, independently
  → CI green                                            → CPO APPROVES
  → /ship <PR>      DevOps merges, tags, deploys
```

Two gates are yours and only yours: **after the spec** (is this the right
thing?) and **before merge** (is this good enough to ship?).
