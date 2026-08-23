# Token Fruit Roadmap

Owned by the CPO. This file is the **only** input to the team. Nothing gets
built that does not start as a line here.

Keep items to one or two lines. Precision is the Product Owner's job — your job
is to say what matters and in what order. If you find yourself writing
acceptance criteria here, stop and run `/groom` instead.

## The arc

area54 is built by the team it ships, so the phases hold in order: a team that
cannot be trusted is not worth improving, and a team that cannot improve is not
worth distributing.

1. **Correct** — the team does the right thing, and cannot do the wrong one.
   Roles, tool scoping, model pins, the shell guard, the merge gate. Largely
   done, and defended by CI rather than by good intentions.
2. **Self-improving** — the team gets better without a human remembering to fix
   it. Evals reach three of eight agents, nothing reads a transcript, and no
   agent definition has ever improved except by hand. **This is the work.**
3. **Distributable** — one team across many products, updated by a version bump
   instead of six copy-pastes.

## Now

<!-- What the team is working on or picking up next. Keep this short —
     three or four items. A long "Now" is a "Next" in disguise. -->

- [ ] TF-019 — The escalation contract. `TEAM.md` says what an agent does when
      it is blocked and nothing about what must never reach the CPO, so agents
      narrate mechanics where they should report an outcome and a decision
- [ ] TF-020 — Learn from the transcripts. Every run leaves one on disk and
      nothing reads it, so an agent definition improves only when a human
      remembers a failure — evidence-gated proposals, never a self-rewrite
- [ ] TF-003 — Package the team as a Claude Code plugin, so a prompt fix reaches
      every product repo by version bump instead of six copy-pastes

## Next

<!-- Committed, not started. -->

- [ ] TF-016 — Evals for the five roles they do not cover. `designer` and
      `devops` have each executed exactly once, and nothing would catch either
      of them degrading
- [ ] TF-017 — The repo does not check itself. A 481-line spec and a 707-line
      ADR for one `<head>` feature both got through; and branch protection
      turns on CI job names that no test pins, over actions still on moving tags
- [ ] TF-010 — Close area52's two Definition-of-Done gaps: ESLint is
      unconfigured (`next lint` is deprecated and prompts interactively), and
      `npm run build` needs DATABASE_URL and the NextAuth secrets
- [ ] TF-008 — Migrate to `claude plugin eval` when early access arrives. It
      has an ablation arm that measures whether the team actually helps versus
      no plugin at all — something this harness cannot do

## Later

<!-- Wanted, not committed. Ideas live here until they earn a promotion. -->

- [ ] Integrate `no-mistakes` as the code-quality gate ahead of PR, with review
      auto-fix off, keeping the Lead and Tester on spec fidelity. Its gate is a
      git remote, so it holds in repos where branch protection is unavailable
- [ ] Per-repo team profiles — not every product needs all seven roles
- [ ] Cost and cycle-time telemetry per feature, so the CPO can see what the
      team costs and where it stalls

## Done

<!-- Shipped. Keep the TF number and the date. -->

- [x] **TF-018** — The merge is a gate that is code, not judgement: six rules, a
      short-lived authorisation naming one PR at one commit, and a guard that
      permits `gh pr merge` only against it — 2026-08-23
- [x] **TF-013** — Close the push-to-main hole the Lead found. A PreToolUse
      guard reads the whole command, because prefix rules cannot — 2026-08-23
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
