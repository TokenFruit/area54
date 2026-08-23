# TF-020: Learn from the transcripts

**Status:** Draft
**Roadmap item:** "TF-020 — Learn from the transcripts. Every run leaves one on disk and nothing reads it, so an agent definition improves only when a human remembers a failure — evidence-gated proposals, never a self-rewrite"
**Author:** Product Owner agent

## Problem

Every session this team runs leaves a full transcript at
`~/.claude/projects/<munged-cwd>/<uuid>.jsonl`, and nothing in area54 opens one.
Telemetry records `hook_event_name`, `session_id`, `tool_name` and `tool_input`
— it answers "how much did that cost", never "did the team do it well". So an
agent definition improves only when the CPO happens to remember a failure and
edits the file by hand, which is how every fix in this repo has happened. Rules
that stopped mattering are never noticed at all: nothing here can tell a
load-bearing instruction from a dead one.

## Outcome

A recurring failure the CPO has *not* remembered reaches him as a concrete,
evidence-backed edit to one agent definition, with the verbatim session quotes
behind it, and he accepts or rejects it in one sitting.

**Whether an accepted edit actually helped is not measurable today, and this
item does not make it so.** Evals reach three of eight agents and no live trial
has ever completed (`CLAUDE.md`), so there is no before/after signal to compare.
What this item *can* measure is relevance: the share of analysed sessions in
which an instruction was cited at all. That finds dead rules, which nothing in
area54 can do now. Proving an edit helped needs TF-016 and a working eval
session; until then the honest claim is "proposed on evidence", not "improved".

## User stories

- As the CPO, I want a repeated failure to arrive as a proposed edit with its
  evidence, so that improving the team does not depend on my memory.
- As the CPO, I want a rule that no session has needed in months to be named as
  dead, so that the definitions shrink as well as grow.
- As the maintainer of a target repo, I want nothing to edit an agent definition
  unattended, so that a deployed team never changes under me.
- As a developer whose sessions are the corpus, I want anything secret-shaped
  removed before a model sees it, so that reading transcripts is not a leak.

## Scope decisions

**Reads:** this repo's transcripts only, by default. The collector takes a repo
path, in the style of `tools/telemetry.py`'s `repos` argument, so pointing it at
area52 is an invocation, not a rewrite — but no target repo is analysed as part
of this item. Association is deterministic only: a session counts when its
recorded `cwd` resolves inside the named repo's worktree. `backpass`'s
best-effort tier is not adopted.

**Proposes edits to:** `.claude/agents/*.md` and nothing else. `team/TEAM.md`
deploys to every target repo (`tools/deploy.py:45`) and `.claude/commands/*.md`
drives the pipeline; an automated proposal against either is a larger blast
radius than a first version has earned. The roadmap line says "an agent
definition", and that is exactly the scope.

**Build, not adopt.** ADR-0001 fixes the stack at Python 3.12 with no runtime;
`backpass` is Node ≥22.5 and needs `acpx` on PATH, and area54 ships as a plugin
that must run on a developer's machine and in CI. It also optimises *one* memory
file, where area54's weights are eight role definitions whose evidence must be
partitioned per agent — the unit of learning differs. Take backpass's
**mechanisms** as the design and write the tool here: verbatim quotes, the
two-session ledger, the bounded step, propose/apply separation, measured
relevance, remembered rejections, and above all the staging-copy diff. That last
one is why this belongs in area54: like `tools/merge_gate.py`, the decision is
code rather than judgement — every hunk is copied out of the real file by
construction, so a proposal cannot describe an edit that isn't there. **This is
the central architectural question and the ADR decides it, not this spec**
(open question 1).

## Acceptance criteria

1. **Given** a transcript store holding sessions from this repo and sessions
   from another directory, **when** the collect step runs against this repo,
   **then** only the sessions whose recorded `cwd` resolves inside this repo's
   worktree are reported, and the report states how many were found and how many
   were skipped.
2. **Given** a store containing a session this tool itself created, **when**
   collect runs, **then** that session is excluded from the corpus and reported
   as self-excluded. The tool must not learn from its own output.
3. **Given** a transcript containing a value matching a secret shape (a token,
   key, or `Authorization` header), **when** it is distilled, **then** that value
   does not appear in the distilled artifact, and no model call has been made
   before distillation completes.
4. **Given** a distilled trace, **when** it is compared with its source, **then**
   every user and assistant turn is present, each tool call is reduced to a
   single summary line, tool output is truncated, and the path to the raw
   transcript is retained so a claim can be checked against the original.
5. **Given** analysis output containing a claim whose quoted evidence does not
   occur verbatim in the transcript it cites, **when** the aggregation step runs,
   **then** that claim is discarded and the count of discarded claims is
   reported.
6. **Given** a gap observed in exactly one session, **when** a proposal is
   generated, **then** that gap does not appear in it. **And given** a second,
   independent session showing the same gap on a later run, **then** it does
   appear — the sighting having persisted between runs.
7. **Given** a run that would produce more than the configured maximum number of
   edits (default 5), **when** it finishes, **then** it fails loudly, naming the
   breach, and writes no proposal. It must not silently truncate to the cap.
8. **Given** a completed propose run, **when** the repository is inspected,
   **then** every file under `.claude/agents/` is byte-identical to before, and
   no file outside the tool's own state directory has been written.
9. **Given** a proposal, **when** each of its hunks is compared against a diff
   of the staging copy taken independently, **then** they agree; a measured
   change that no proposed edit accounts for, or a proposed edit naming no
   measured change, fails the run.
10. **Given** a run in which the synthesis step modified a staged file outside
    `.claude/agents/` — including a staged `TEAM.md` or command file — **when**
    the run finishes, **then** it fails and names the out-of-scope path.
11. **Given** a proposal, **when** the apply step runs, **then** it presents each
    edit with its diff and its verbatim evidence including the session it came
    from, requires a separate accept or reject per edit, and writes only the
    accepted ones. **And given** no attached terminal (CI, or piped input),
    **then** it refuses to run and exits non-zero. Nothing may apply an edit
    unattended.
12. **Given** an edit the CPO rejected, **when** the next run executes over the
    same corpus, **then** it is not proposed again. **And given** a new session
    supplying evidence for it, **then** it may be proposed again, and the report
    says it is a re-proposal.
13. **Given** a completed analysis, **when** the report is read, **then** it
    gives, per agent definition, the share of analysed sessions in which each
    instruction was cited, and lists instructions cited in none as dead-rule
    candidates. A removal proposed for one is an edit like any other and passes
    the same evidence and staging gates.
14. **Given** no transcripts for the repo, a store that is missing or has an
    unrecognised shape, or a transcript the distiller cannot parse or redact,
    **when** a run executes, **then** it reports that plainly, writes no
    proposal, and makes no model call over the affected transcript — it never
    passes unredacted text through.
15. **Given** lint, typecheck and `pytest`, **when** they run in CI, **then**
    they pass, and every check introduced here has a unit test covering both its
    passing and its failing case, over fixture transcripts committed to the repo.

### How each criterion is verified

**Mechanically, by `pytest` over fixture transcripts:** 1, 2, 3, 5, 6, 7, 8, 9,
10, 12, 14, 15. These exercise the deterministic layer — collection,
distillation, redaction, aggregation, the ledger, the gates — none of which
needs a model.

**Human-observable:** 11 (the terminal-refusal half is mechanical; that the
review surface makes an accept-or-reject decision *easy* is a read), and 13's
usefulness — the arithmetic is mechanical, whether a dead-rule candidate is
genuinely dead is a judgement.

**Mixed:** 4. Turn preservation, one-line tool calls and the retained path are
mechanical; whether the distillation kept the signal is a human read of a real
trace.

**Stated on purpose.** As with TF-019, `team/TEAM.md`'s Definition of Done item
1 cannot be met literally: the quality of a model's analysis is not testable, and
**no live model call can complete on this account today** — the CLI's OAuth
session is expired (`CLAUDE.md`), the same condition that blocks the eval
harness. Every criterion above is therefore satisfiable with the model layer
stubbed, and none may be read as requiring a live analysis run. The Tester
should record that exception rather than choose between a false Pass and a Fail.

## Out of scope

- **Analysing target repos.** The path argument exists; running it against
  area52 is a separate item.
- **Editing `team/TEAM.md` or `.claude/commands/*.md`.** Criterion 10 forbids
  it. Widening the target set is a later item once the loop has proven itself.
- **Any harness but Claude Code.** backpass reads six stores; area54 has one.
- **Skill extraction and a token budget for the definitions** — backpass's
  overflow valve. It presumes a budget nobody here has set.
- **Proving an edit helped.** Needs TF-016 and a session that can complete a
  trial. See Outcome.
- **Running this automatically, on a schedule or in CI.** Criterion 11 makes it
  attended by construction.
- **Recency weighting and sampling caps.** area54's transcript volume does not
  yet need them; add when a run is too slow to sit through.
- **Instrumenting the escalation contract from transcripts.** TF-019 names this
  as future work; it is a consumer of this tool, not part of it.

## Open questions

Each blocks approval.

1. **Build, adopt, or wrap?** The recommendation above is *build*, on ADR-0001
   grounds. The honest cost: it is a fortnight of work that npm would install in
   a minute. Confirm the ruling, and whether an ADR-0003 records it. If the
   answer is *adopt*, most criteria above are re-expressed as configuration and
   the item shrinks sharply.
2. **Is `.claude/agents/` the right and only edit target?** Criterion 10 depends
   on this answer.
3. **Is area54-only correct for a first version**, with target repos deferred?
4. **Who accepts an edit — the CPO only?** And is this a standalone command the
   CPO runs, or a stage of `/deliver`? The recommendation is standalone: it is
   maintenance of the team, not delivery of a feature, and it must never sit
   between the two gates.
5. **Where does the state live — the gap ledger, rejection memory, and cached
   evidence?** Committing them makes the two-session rule work across machines
   and survives a clone; ignoring them keeps transcript-derived text out of git.
   The evidence quotes are excerpts of real sessions, so this is a privacy
   decision, not a convenience one, and it is the CPO's.
6. **What model, and what cost ceiling per run?** backpass uses cheap analysis
   and expensive synthesis. area54 pins models per agent (TF-002); this tool is
   not an agent. Also: with OAuth expired, does the CPO accept this item shipping
   with the model layer exercised only by stub, as criterion 15 implies?
7. **Does this ship to target repos in the deploy `PAYLOAD`,** or stay an area54
   tool? It edits agent definitions, which every target repo has.
8. **Must an accepted edit arrive with an eval case?** It would make the loop
   self-verifying over time and would make each acceptance considerably more
   expensive. Not assumed either way above.

## Dependencies

- **None blocking.** The transcript store, `tools/telemetry.py`, `tools/evals/`
  and `tools/validate.py` all exist.
- **ADR-0003 (not yet written)** — build versus adopt, per open question 1.
- **TF-016** (evals for the five uncovered roles) and **TF-008** (`claude plugin
  eval`) are what would eventually let "did the edit help" be answered. Neither
  is required to ship this. A working CLI session is required to *run* the tool
  for real, but not to accept it.
