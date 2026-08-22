# Token Fruit Roadmap

Owned by the CPO. This file is the **only** input to the team. Nothing gets
built that does not start as a line here.

Keep items to one or two lines. Precision is the Product Owner's job — your job
is to say what matters and in what order. If you find yourself writing
acceptance criteria here, stop and run `/groom` instead.

## Now

<!-- What the team is working on or picking up next. Keep this short —
     three or four items. A long "Now" is a "Next" in disguise. -->

- [ ] TF-002 — Pin exact model IDs in every agent, so a model upgrade cannot
      silently change the whole team overnight
- [ ] TF-003 — Package the team as a Claude Code plugin, so a prompt fix reaches
      every product repo by version bump instead of six copy-pastes

## Next

<!-- Committed, not started. -->

- [ ] TF-004 — Deterministic validators over agent definitions: frontmatter,
      tool scoping, and the invariant that no agent holds both review and write
      authority. Replaces the stack-detection placeholder in CI
- [ ] TF-005 — Eval harness: fixture repos with planted defects. Does the Lead
      catch the bug? Does the PO write falsifiable criteria? Does the Tester
      refuse to weaken a failing test?
- [ ] TF-006 — Deploy to the first target repo. Gempli (`area53`) — it is real,
      active, and already has standards to be judged against

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
