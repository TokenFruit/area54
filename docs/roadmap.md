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

- [ ] TF-016 — Evals for the five untested roles. `designer`,
      `builder-backend` and `devops` have never executed once, and `/ship` has
      never run — the role closest to production is the least proven
- [ ] TF-017 — Size discipline. A 481-line spec and a 707-line ADR for one
      `<head>` feature both got through; nothing constrains output length




- [ ] TF-010 — Close area52's two Definition-of-Done gaps: ESLint is
      unconfigured (`next lint` is deprecated and prompts interactively), and
      `npm run build` needs DATABASE_URL and the NextAuth secrets


- [ ] TF-008 — Migrate to `claude plugin eval` when early access arrives. It
      has an ablation arm that measures whether the team actually helps versus
      no plugin at all — something this harness cannot do

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
- [x] **TF-014** — Validate the configuration that can hurt you: permission
      rules, hook existence, and payload completeness — 2026-08-23
- [x] **TF-015** — Telemetry: a hook records pipeline events, so "what did that
      feature cost" is answerable from data — 2026-08-23
- [x] **TF-009** — First real feature end to end in area52: TF-001 shipped
      through spec, ADR, build, review and two defect rounds — 2026-08-23
- [x] **TF-007** — Evals run live; four cases pass — 2026-08-23
- [x] **TF-012** — Redeployed to area52 with `/deliver` and the guard — 2026-08-23
- [x] **TF-011** — Publish the sequence and make the team run it: `/deliver`
      chains the pipeline to two CPO gates, agents name their successors, and
      shell permissions stop them stalling — 2026-08-23
- [x] **TF-006** — Deploy to the first target repo. area52 (Promptico), named
      by the CPO — installer, portable constitution, and CI — 2026-08-23
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
