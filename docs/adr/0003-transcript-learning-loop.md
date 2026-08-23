# ADR-0003: Build the learning loop here, and let no model text reach a file

**Status:** Proposed
**Implements:** TF-020
**Supersedes:** none

## Context

TF-020 asks for a loop that reads this repo's Claude Code transcripts and turns
recurring failures into proposed edits to `.claude/agents/*.md`, gated by the
CPO. Its resolved questions are rulings, and this ADR is written under them.

Facts that constrain the choice, each checked against this branch:

- **The store's shape is known.** A one-word `claude -p` run I made on
  2026-08-24 wrote a session file of **39,622 bytes**, of which the two
  substantive turns are ~3.1 KB and the remaining ~34 KB is harness scaffolding
  on `attachment` lines (`deferred_tools_delta` 19 KB, `skill_listing` 8 KB,
  `agent_listing_delta` 5 KB). Line `type`s observed: `user`, `assistant`,
  `attachment`, `ai-title`, `last-prompt`, `atis-latch`, `queue-operation`.
  `user` and `assistant` lines carry `cwd`, `gitBranch`, `sessionId`; the
  scaffolding lines do not.
- **`--session-id <uuid>` is honoured** — that run landed under exactly the UUID
  I passed. Self-exclusion (criterion 2) needs no prompt tagging.
- **`--output-format json` returns a machine cost field** — that run returned
  `"total_cost_usd":0.0303034` plus a `modelUsage` map of per-model `costUSD`.
- The CLI has `--disallowed-tools` and `--permission-mode`, and **no
  `--max-turns`**: a synthesis call cannot be turn-bounded.
- `tools/evals/runner.py:130-145` already invokes the CLI, but builds argv from
  an `EvalCase` and `load_agents()` — neither of which this tool has.
- Model pinning (TF-002) is enforced on agent frontmatter only,
  `tools/agents.py:97` against `tools/agents.py:21-34`, so nothing reaches a
  tool.
- `tools/telemetry.py:47-56` skips malformed log lines. Right for cost
  reporting; wrong here, where a line the tool cannot parse is one it cannot
  redact. `tools/telemetry.py:116-120` is the `repos` shape question 3 names,
  and `tools/settings.py:205-209` records why that tool stays in area54 —
  question 7 puts this one in the same category.
- ADR-0001 and ADR-0002 stand unchanged, and `tools/merge_gate.py:208-210` —
  "an unevaluated gate is a failed gate" — is the rule this item extends.

## Decision

### 1. Build, not adopt. The ruling holds, and here is the arithmetic

**What adopting `backpass` would buy.** A debugged distiller, a gap ledger with
expiry, a rejection memory, propose/apply separation, a staging-copy diff with
mechanical gates, a two-tier model ladder, and a rendered review surface — the
whole mechanical spine of this item, working today, for one `npm install`.

**What it would cost.**

- **A second toolchain.** Node ≥22.5 plus `acpx` on PATH, in a repo whose stack
  decision (ADR-0001 §2) was one tooling language. CI gains a Node setup step to
  run a tool CI is forbidden to run (criterion 11, and the spec's "Out of
  scope"): paid everywhere, used in one place.
- **The wrong unit of learning.** backpass optimises the first existing file
  from `memoryFiles` (`AGENTS.md`, else `CLAUDE.md`) under a token budget.
  area54's weights are eight role definitions, evidence partitioned per agent,
  edit target `.claude/agents/*.md` — a set backpass has no concept of.
  Criterion 10 requires the run to **fail** when a staged `TEAM.md` changes; to
  backpass, `CLAUDE.md` is a candidate weights file.
- **Carrying a disabled half.** The token budget and skill extraction are out of
  scope here, and backpass's default edit cap is *derived* from budget overage.
  Adopting means configuring off the machinery that drives its central loop.
- **Six adapters, five unused**, and the best-effort association tier the spec
  rejects is a live code path.

**The reckoning.** The genuinely reusable share is the distiller, the ledger and
the staging diff. Rewritten here against one store and eight files those are
roughly 120, 100 and 150 lines of Python over `json`, `re`, `difflib` and
`hashlib` — no new dependency, all four standard library. The rest is out of
scope or shaped for a different target. A permanent second toolchain is the
worse trade, and the fortnight is not a fortnight of the parts we would keep.

**Also rejected:** vendoring backpass's TypeScript (keeps the Node runtime,
adds a fork); shelling out to `npx backpass` for distillation only (the
toolchain cost, none of the leverage).

### 2. `tools/learn/`, one entry point, two writing-relevant invocations

A package in the shape of `tools/evals/`, one module per concern: `store.py`
(association, self-exclusion), `distil.py` and `redact.py`, `model.py` (build
and run one CLI call, parse its cost), `evidence.py` (the analysis pass and its
cache), `instructions.py` (parse a definition into addressable instructions),
`aggregate.py` (verbatim verification, clustering, relevance), `ledger.py`,
`propose.py` (stage, synthesise, measure, gate), `apply.py`, `__main__.py`.

Subcommands `scan`, `propose`, `apply`, `status` on one `-m` target, matching
`python -m tools.telemetry` and `python -m tools.evals`. But `propose` and
`apply` are **separate invocations**, separate processes, per question 4:
`propose` holds no code path that writes outside its state directory, and
`apply` makes no model call and reads only `proposal.json`.

`tools/validate.py` is untouched — this is a tool, not a check.

### 3. Distillation, and redaction before any model sees anything

**Reduction, in order, per transcript:**

1. Parse every line as JSON. **A line that is not valid JSON fails the whole
   transcript**, which is excluded and named (criterion 14). This departs from
   `tools/telemetry.py:53-56` deliberately: skipping a bad line there loses a
   cost datum; skipping it here forwards its neighbours while pretending the
   file was understood.
2. Keep `user` and `assistant` lines; **drop every other `type` by allowlist**,
   counting them. An unrecognised type is unredactable content, and a denylist
   forwards the next type the harness invents.
3. Per content block: `text` verbatim; `thinking` verbatim, truncated (criterion
   4 requires every assistant turn, and thinking is where an agent talks itself
   out of a rule); `tool_use` collapsed to one line, `tool: <name> <single-line
   argument digest>`; `tool_result` truncated to 1,000 characters with a
   `[+N characters]` marker.
4. Prepend a header: session id, `cwd`, `gitBranch`, first and last timestamp,
   and **the absolute path to the raw transcript** (criterion 4).
5. Redact over the whole distilled text, as the last step before it is written.

Step 2 alone is a ~92% reduction on the measured sample.

**Redaction** is shape-based, in `redact.py`, over distilled text only. Rule
classes: known credential prefixes (Anthropic, GitHub PAT/OAuth, AWS access key,
Slack, Google API, GitLab PAT); `Authorization: <scheme> <value>` headers; PEM
private-key blocks from opening to closing marker; assignments whose left side
matches `[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z_]*` in env or CLI
shape; and URL userinfo. Each match becomes `[redacted:<rule>]`, and the
per-transcript count is reported.

**Rejected: an entropy heuristic.** A transcript is full of SHAs, UUIDs and
base64 content, so a high-entropy detector is mostly false positives — and a
false positive silently destroys a verbatim quote, the one thing this design
rests on being exact.

**What redaction guarantees:** no value matching a listed shape reaches a model
call, because distillation of *every* selected transcript completes before the
first call (criterion 3), and the raw file is never an argument to `model.py`.
If a rule raises, or the distilled text still matches any rule after
substitution — an idempotence assertion — that transcript is excluded and named,
and no call is made over it (criterion 14).

**What it cannot guarantee:** a secret with no shape. A bare password, a
customer name, an internal hostname, a private URL. This is a filter, not a
boundary. The boundary is that the call goes through a CLI the developer has
already authenticated, on their own machine, to the same vendor whose harness
wrote the transcript.

### 4. The staging-copy diff: no text can come from the model

1. Hash every `.claude/agents/*.md` (SHA-256) and hold the map.
2. Copy each file byte-for-byte into `.claude/learn/staging/`, and the same
   bytes into `.claude/learn/staging/.baseline/`. The baseline is what the diff
   is taken against — not the repo, which is not read again mid-run.
3. Run synthesis with `cwd` set to the staging directory and `--allowed-tools
   Read Edit Write Glob Grep`. Claude Code confines file tools to `cwd` and no
   `--add-dir` is granted, so **the repo is unreachable** from that session. The
   aggregated evidence travels in the prompt instead. Cost: synthesis cannot
   open a raw transcript to check a claim — acceptable, because every claim was
   verified verbatim in §7 step 5, deterministically, before synthesis ran.
4. **Measure.** Per staged file, `difflib.SequenceMatcher` against its
   baseline. Each non-equal opcode group becomes
   `MeasuredChange(id, path, before, after)`, `before` sliced from the baseline
   bytes, `after` from the staged file bytes.
5. **Annotate.** A second call is shown the changes *by id* and returns JSON:
   `{id, title, rationale, evidence: [{session_id, quote}], covered_by_eval}`.
   That last field is question 8's eval worklist.

**The invariant, checkable in one grep:** the annotation dataclass has **no
field carrying file text**, and `MeasuredChange.before`/`.after` are assigned in
exactly one function, `measure_changes()`, from bytes read off disk. There is no
code path from a model response to a file write. `apply` writes `after`. A
proposal therefore cannot describe an edit that is not in the staged file, nor
splice in one that is not in the diff.

**The gates, all fail-loud, none negotiable:**

| Gate | Criterion |
| --- | --- |
| Every measured change annotated exactly once; every annotation names a real id | 9 |
| Every changed staged path under `.claude/agents/`, and existed before | 10 |
| Edit count ≤ `--max-edits` (default 5) — **fail, never truncate** | 7 |
| Every annotation carries ≥1 quote occurring verbatim in a distilled trace | 5 |
| An addition's gap has sightings in ≥2 distinct sessions | 6 |
| Re-hash `.claude/agents/*.md` against step 1; any change fails and names it | 8 |

A breach triggers at most **two** re-prompts naming the exact breach, then the
run fails and saves the rejected proposal. With no `--max-turns`, the retry
count and the spend ceiling are the only bounds on the session.

### 5. State: references in git, text on disk only

Under `.claude/learn/`, which mixes tracked and ignored exactly as `.claude/`
already does (`settings.json` tracked, `telemetry.jsonl` ignored).

| Path | In git | Holds |
| --- | --- | --- |
| `gap-ledger.json` | **yes** | Sightings: `gap_id`, `agent`, `instruction`, `session_id`, `date`; plus `resolved_gaps`, `self_sessions` |
| `rejections.json` | **yes** | Per rejected edit: `gap_id`, `agent`, `instruction`, `rejected_on`, `diff_digest`, `evidence_sessions` |
| `README.md` | **yes** | Why two of these are tracked |
| `evidence/<session>.json` | no | Distilled trace, model verdict, quotes |
| `proposal.json` | no | Measured changes and annotations; what `apply` reads |
| `staging/`, `staging/.baseline/` | no | §4 |
| `prompts/<run_id>/` | no | The exact prompts sent, for diagnosis |

`gap_id` is `sha256(agent + "\0" + normalised gap label)`, truncated: the digest
travels, the label does not. `instruction` is a **reference** —
`lead.md#Stop conditions[2]` — never an excerpt. Nothing tracked contains
transcript text, which is question 5 exactly.

**The two-session rule, from references alone.** A gap graduates when
`|{s.session_id for s in sightings if s.gap_id == g and s.date ≥ cutoff}| ≥ 2`,
over a 90-day cutoff — set cardinality over the tracked ledger, no text
consulted. A sighting retires
when its `gap_id` enters `resolved_gaps` on an accepted edit, and expires at 90
days.

**Re-proposal (criterion 12).** An edit whose `gap_id` matches a rejection is
suppressed, **unless** its evidence session set holds an id absent from that
rejection's `evidence_sessions`; then it is proposed and marked a re-proposal.

**The cost:** on a fresh clone, `status` shows digests and counts, not prose.
The ledger is auditable for shape, not content. That is the price of keeping
transcript excerpts out of a repo that deploys.

### 6. Model invocation, pinning, and measured spend

Pins are module constants in `tools/learn/model.py`, not frontmatter, because
this is not an agent and `tools/agents.py:97` does not reach it:

- **Analysis** — `claude-sonnet-5`, one call per transcript, the bulk of spend.
  Not Haiku: this pass judges instruction-following over a long trace, and a
  wrong verdict poisons the aggregate silently. Configurable down.
- **Synthesis** — `claude-opus-5`, one call, where a bad judgement is expensive.

A unit test asserts both are in `tools.agents.PINNED_MODELS`, so TF-002's
no-floating-alias rule is enforced here by import rather than by frontmatter.

Analysis calls run with `--disallowed-tools` covering every file and shell tool
and `cwd` set to an empty temp directory: the trace is in the prompt, and there
is nothing to reach even if a tool were granted.

**Spend is measured by the tool.** Every call uses `--output-format json`; the
tool reads `total_cost_usd` off the envelope and sums it. That is the
*harness's* accounting read from a machine field, not a number a model wrote —
which is the distinction question 6 draws. **If the field is absent, the call
counts as unknown cost and the run stops** rather than continuing unmeasured.

**The ceiling** is `--max-spend-usd`, default `1.00`, checked *before* each
call: if `spent + worst_case > ceiling`, stop. `worst_case` is the largest cost
observed so far, or a seed constant for the first call.

Every call is given an explicit `--session-id`, and **that id is written to
`self_sessions` before the call is made**, never after. A crash mid-call must
still leave the session excluded (criterion 2): the synthesis session runs with
`cwd` inside this repo, so it would otherwise pass criterion 1's filter on the
next run and become the tool's own training data.

### 7. Order of operations, and what each failure does

Ordering is a safety property in the three steps marked ★.

1. Hash every `.claude/agents/*.md`.
2. Collect: keep sessions whose recorded `cwd` resolves inside the repo
   worktree, drop `self_sessions`, report found / skipped / self-excluded.
3. ★ Distil and redact **every** selected transcript, to completion, before any
   model call (criterion 3). A barrier, not a pipeline: it costs latency and
   buys the criterion.
4. Analyse, cached per `(distilled digest, digest of all agent files)`, so
   editing a definition re-computes evidence and an unchanged run is free.
5. ★ Verify every claim's quote verbatim against its distilled trace; discard
   the rest and report the count (criterion 5). Deterministic, before synthesis.
6. Update the ledger, graduate gaps, apply the rejection filter.
7. Stage, synthesise, measure, annotate, gate (§4).
8. ★ Re-hash and compare against step 1 (criterion 8).
9. Write `proposal.json`. Nothing under `.claude/agents/` is touched.

| Failure | Response |
| --- | --- |
| Store missing, unrecognised shape, or no transcripts for this repo | Report plainly, no proposal, no model call (criterion 14) |
| One transcript unparseable, or redaction not idempotent | Exclude and name it, continue over the rest; no call over it |
| Analysis call fails or returns non-JSON | Retry once, then mark that transcript failed — the corpus is now partial, see below |
| Synthesis call fails | End the run, no proposal |
| Ceiling reached mid-run | Stop, keep the evidence cache, **write no proposal**, report analysed-of-total and spend |
| Any gate breached | Two re-prompts, then fail loudly and save the rejected proposal |

**A partial corpus never produces a proposal.** Not caution: criterion 13's
dead-rule finding is arithmetic over "analysed sessions", and an instruction
cited in none of three analysed sessions is not evidence of a dead rule. The
denominator has to be the whole corpus or the finding is false.

### 8. `apply` is terminal-only

One card per edit in the terminal — the diff, the verbatim evidence with its
session id, accept or reject, per edit (criterion 11). It refuses and exits
non-zero unless both `stdin` and `stdout` are TTYs.

No rendered review surface. backpass serves HTML; here that is a second artifact
to build, and it weakens the TTY refusal that makes criterion 11 mechanical.
**This overrides the parallel design if that specifies a rendered surface** —
an architecture call, not one to hand back.

## Data model

No database (ADR-0001). The persistent structures are the two tracked JSON files
in §5. In-process types: `Session`, `DistilledTrace`, `Claim`, `Sighting`,
`MeasuredChange`, `Annotation`, `ProposedEdit`.

`instructions.py` defines the addressable unit criterion 13 needs and the spec
leaves open: **one top-level Markdown list item, or one `##`/`###` section with
no list**, addressed as `<file>#<heading>[<n>]`, parsed by the line-shape
approach of `tools/constitution.py:110` — which already counts top-level items
correctly across wrapped lines and sub-bullets. Relevance is computed per agent
over **the sessions in which that agent ran**: citing `lead.md#Stop conditions`
in a session where the Lead never ran is not a signal. An interpretation of
criterion 13, flagged so the CPO can reverse it.

## Interfaces

| Surface | Contract |
| --- | --- |
| `python -m tools.learn scan [repo…]` | Association table: found, skipped, self-excluded. No model call, never writes |
| `python -m tools.learn propose [repo] [--max-edits N] [--max-spend-usd D]` | §7 steps 1-9. Writes only under `.claude/learn/`. Exit 1 on any gate breach or ceiling stop |
| `python -m tools.learn apply` | The CPO gate. Refuses without a TTY. Writes accepted hunks only |
| `python -m tools.learn status` | Ledger and cache state; digests, not prose |
| `.claude/learn/proposal.json` | The contract between the two processes |

`tools/validate.py`, `tools/deploy.py`'s `PAYLOAD`, and every existing module
are unchanged.

## Dependencies

**None added.** `json`, `re`, `difflib`, `hashlib`, `subprocess`, `pathlib`,
`uuid` — standard library, per CLAUDE.md's fifty-line rule and ADR-0001's
dependency table. Rejected: `unidiff` and similar (`difflib` already produces
the opcode groups this design measures, and a library that *applies* patches is
the exact capability this design must not have); `detect-secrets` or `gitleaks`
(a process and a rule database for five rule classes over text already in
memory).

## Migration and rollout

**Backward compatible.** New package, new gitignore entries, no existing file
changes behaviour. `git revert` removes it whole. In order:

1. `store.py`, `distil.py`, `redact.py`, `instructions.py`, `ledger.py`, with
   tests over committed fixture transcripts. All deterministic, no model.
2. `.gitignore` entries for `.claude/learn/{evidence,staging,prompts}/` and
   `proposal.json`; `README.md` and two empty tracked JSON files.
3. `model.py`, `evidence.py`, `aggregate.py`, `propose.py` — gates tested
   against a fake runner, in the shape of `tools/evals/runner.py:93`.
4. `apply.py`.
5. `CLAUDE.md` Commands table: two rows, the second marked attended-only.

Steps 1-4 each land green. Not deployed: question 7 keeps it here, and
`tools/settings.py:205-209` is the precedent — nothing is added to `PAYLOAD`.

## Risks

**A model confabulates influence.** Likely and unfixable. The mitigations —
verbatim quotes checked in code, the two-session rule, the staging diff, the CPO
gate — bound *fabricated text*, not *fabricated causation*. A quote can be real
and its attribution wrong. Accepted; the CPO reads the evidence, not the title.

**Redaction misses a shapeless secret.** Certain, over enough transcripts. §3
states the limit rather than mitigating it, and it is why the call goes to an
already-authenticated harness rather than anywhere new. Relatedly,
`.claude/learn/evidence/` accumulates transcript text on disk with no expiry —
not a leak into git, but a second copy of what the raw store already holds.

**The transcript format is undocumented and will change.** Likely within months.
Mitigated by §3 step 2's allowlist, which fails toward dropping content rather
than forwarding it, and by pinned fixtures. A rename of `user`/`assistant`
yields an empty corpus and a plain report, which is loud.

**The tool learns from its own sessions.** Guarded by `self_sessions` written
before the call. The residual is a session from a crashed run whose id never
reached disk — bounded, because the write precedes the call.

**Sonnet-5 on every transcript is the cost centre.** With no sampling cap (out
of scope), a large corpus can hit the ceiling and stop the run repeatedly, with
no proposal ever produced. Mitigated by the evidence cache making each run
cheaper than the last; if it bites, the fix is the sampling the spec deferred.

## Alternatives considered

**Adopt `backpass`.** §1, at length.

**One invocation that proposes and applies behind `--yes`.** Rejected by
question 4, and rightly: a process that can both propose and write is one bug
from writing unattended.

**Let synthesis read the repo read-only for grounding**, as backpass does.
Rejected: it puts the real `.claude/agents/` inside the tool boundary for
context that §7 step 5 has already verified. The staging directory being the
*entire* reachable filesystem is stronger than a convention about which paths
are writable.

**Have the model return edited text and splice it in.** Rejected — the failure
mode the whole item exists to prevent, named here so the rejection is on record.

**A ledger holding verbatim excerpts, so a clone is self-contained.** Rejected
by question 5: durability and privacy are separated rather than traded.

**An HTML review surface.** §8.

**Reuse `ClaudeCliRunner` (`tools/evals/runner.py:106`).** Rejected: it builds
argv from an `EvalCase` and `load_agents()`, copies a fixture tree and captures
changed files; generalising it would make the eval harness carry this tool's
cost accounting. The approach is reused, the class is not. **A single
`tools/learn.py`** is likewise rejected — ten concerns, of which redaction, diff
measurement and the gates each need their own test module.

**Cut for length**, and named so nobody thinks they were missed: the exact
redaction regexes (classes are specified; patterns are a Builder's choice under
the idempotence assertion), the full CLI flag list, both prompt texts, and the
`status` output format.

## Spec findings — reported, not fixed

1. **The spec contradicts itself on whether a live call can complete.** Lines
   151-157 say "no live model call can complete on this account today — the
   CLI's OAuth session is expired"; resolved question 6 (lines 222-224) says it
   was re-authenticated on 2026-08-23 and criterion 15 "should be read against a
   working session". Question 6 is correct — I made a live call on 2026-08-24
   (see Context). `CLAUDE.md`'s eval paragraph carries the same stale claim.
2. **Criterion 8 is violated by construction as literally written.** "No file
   outside the tool's own state directory has been written" — but every model
   call causes the harness to write a transcript under `~/.claude/projects/`.
   Read it as scoped to the repo worktree, which is plainly what it means; a
   Tester writing to the literal text would fail every passing run.
3. **Criterion 13 defines neither "instruction" nor the denominator.** The Data
   model section states the interpretation this ADR builds to. An
   interpretation, not a correction.
