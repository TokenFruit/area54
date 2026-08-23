# TF-020 — copy

Every string the CPO reads. Written once here so it is not invented eight times
in the code. `{braces}` are substitutions.

**House voice**, consistent with `tools/telemetry.py` and `tools/merge_gate.py`:
plain sentences, no exclamation, no praise, no apology. A failure names what
happened and what to do next — never an error class alone, never a traceback.
British spelling. The tool describes its own limits honestly; it never claims an
edit will help, only that it is proposed on evidence.

---

## S1 — progress

| Key | String |
| --- | ------ |
| `phase.collect` | `Collecting transcripts for {repo_name}…` |
| `phase.collect.done` | `  collected           {in_repo} in this repo, {other} elsewhere, {self} self-excluded` |
| `phase.distil` | `Distilling and redacting {n} transcript(s). No model call is made until this finishes.` |
| `phase.distil.done` | `  distilled           {ok} of {n}   ({redacted} value(s) redacted)` |
| `phase.distil.skip` | `  skipped             {session}  ({reason})` |
| `phase.analyse` | `Analysing {n} transcript(s) with {model}.` |
| `phase.analyse.item` | `  [{i}/{n}] {session}  {elapsed}  spent {spend} of {ceiling}` |
| `phase.analyse.done` | `  analysed            {ok} of {n}` |
| `phase.aggregate.done` | `  aggregated          {kept} claim(s) kept, {discarded} discarded as not verbatim` |
| `phase.synthesise` | `Synthesising with {model} against a staging copy. No file in this repo is touched.` |
| `phase.synthesise.done` | `  synthesised         {edits} candidate edit(s)` |

---

## S2 — the run report

### Corpus and outcome

| Key | String |
| --- | ------ |
| `report.header` | `── learn: {repo_name} ──` |
| `report.partial.banner` | `This run reasoned over {ok} of {n} sessions. {skipped} were skipped; see below.` |
| `report.skipped.head` | `Skipped transcripts:` |
| `report.skipped.item` | `  {session}  {reason}` |
| `reason.unparseable` | `could not be parsed — not sent to any model` |
| `reason.unredactable` | `redaction failed — withheld, not sent to any model` |
| `reason.self` | `written by this tool — excluded so it cannot learn from itself` |
| `reason.out_of_repo` | `cwd resolves outside this repo` |
| `report.discarded` | `{n} claim(s) discarded: the quoted evidence does not occur verbatim in the transcript cited.` |
| `report.spend` | `Spent {spend} of a {ceiling} ceiling, measured by this tool.` |
| `report.written` | `Proposal written to {path}` |
| `report.next` | `Review it with:  python -m tools.learn apply` |

### Sightings

| Key | String |
| --- | ------ |
| `sightings.head` | `Sightings (a gap is proposed at two independent sessions):` |
| `sightings.item` | `  {n} of 2   {agent}: {gap}` |
| `sightings.promoted` | `  {n} of 2   {agent}: {gap}   → proposed` |

### Empty states

| Key | String |
| --- | ------ |
| `empty.no_sessions` | `No sessions for this repo in the transcript store.` |
| `empty.no_sessions.detail` | `Looked in {store}. Found {other} session(s) belonging to other directories, so the store is readable — this repo simply has none yet.` |
| `empty.nothing_new` | `Nothing new to propose. {analysed} session(s) analysed; no gap has been seen in two independent sessions yet.` |
| `empty.nothing_new.detail` | `The sightings above are recorded. A gap at 1 of 2 will be proposed the next time it appears.` |
| `empty.all_suppressed` | `{n} candidate gap(s) were suppressed: you rejected each of them before and no new session provides fresh evidence.` |
| `empty.no_proposal` | `No proposal written.` |

### Gates and failures

| Key | String |
| --- | ------ |
| `gate.line` | `  [{PASS\|FAIL}] {name:18} {detail}` |
| `gate.ceiling.name` | `edit ceiling` |
| `gate.ceiling.fail` | `{proposed} edits proposed, ceiling is {max}` |
| `fail.ceiling` | `::error::Refusing: {proposed} edits proposed against a ceiling of {max}.` |
| `fail.ceiling.detail` | `No proposal was written. It was not truncated to the cap — a run this large is a signal about the corpus, not a list to trim. Raise the ceiling deliberately with --max-edits {n} if you mean to review that many in one sitting.` |
| `gate.staging.name` | `staging agreement` |
| `fail.staging.orphan_change` | `::error::Refusing: {file} changed in the staging copy, and no proposed edit accounts for the change.` |
| `fail.staging.orphan_edit` | `::error::Refusing: a proposed edit to {file} names a change that is not present in the staging copy.` |
| `fail.staging.detail` | `A proposal must describe exactly the change that was measured. No proposal was written.` |
| `gate.scope.name` | `edit scope` |
| `fail.scope` | `::error::Refusing: the synthesis step staged a change to {path}.` |
| `fail.scope.detail` | `Only files under .claude/agents/ may be proposed. No proposal was written.` |
| `fail.budget` | `::error::Stopped: the {ceiling} cost ceiling was reached after {done} of {n} transcripts.` |
| `fail.budget.detail` | `Spent {spend}. No proposal was written. Raise the ceiling with --budget, or narrow the corpus.` |
| `fail.store_missing` | `::error::No transcript store at {store}.` |
| `fail.store_shape` | `::error::The transcript store at {store} is not in a shape this tool recognises.` |
| `fail.store_shape.detail` | `Nothing was sent to a model. If the store layout has changed, this tool needs updating rather than working around.` |
| `fail.store_perm` | `::error::Cannot read the transcript store at {store}: permission denied.` |
| `fail.state_unwritable` | `::error::Cannot write to {path}: permission denied.` |
| `fail.state_unwritable.detail` | `The analysis is complete but cannot be saved, and the {spend} it cost is lost. Fix the permission and re-run.` |
| `fail.offline` | `::error::The model call failed: {detail}` |
| `fail.offline.detail` | `Collection, distillation and redaction completed and cost nothing. Re-running repeats only those local steps before trying again.` |

---

## S3 — relevance and dead rules

| Key | String |
| --- | ------ |
| `relevance.head` | `Instruction relevance, over {n} analysed session(s):` |
| `relevance.agent` | `  {agent}` |
| `relevance.item` | `    {cited}/{n}   {instruction}  ({file}:{line})` |
| `relevance.all_cited` | `    every instruction was cited at least once` |
| `relevance.dead.head` | `  Dead-rule candidates — cited in no analysed session:` |
| `relevance.dead.item` | `    {instruction}  ({file}:{line})` |
| `relevance.dead.no_edit` | `    (no removal proposed — this is information, not a pending decision)` |
| `relevance.unmeasured` | `  Unmeasured — no session in this corpus involved these agents: {agents}` |
| `relevance.unmeasured.note` | `  Unmeasured is not dead.` |
| `relevance.too_few` | `Relevance not reported: {n} analysed session(s) is too few for a citation share to mean anything.` |
| `relevance.failed` | `  {agent}: citation matching failed ({detail}). Omitted from the candidate list rather than reported as dead.` |

---

## S5 — `apply`, preamble

| Key | String |
| --- | ------ |
| `apply.header` | `── learn: review {n} proposed edit(s) ──` |
| `apply.provenance` | `From a run on {date} over {sessions} session(s). {reproposals} re-proposal(s).` |
| `apply.partial.banner` | `That run reasoned over {ok} of {total} sessions.` |
| `apply.legend` | `Per edit:  a accept · r reject · s skip · v view full evidence · ? help · q quit` |
| `apply.legend.note` | `Nothing is written until every edit is decided and you confirm.` |
| `apply.no_proposal` | `::error::No proposal to apply.` |
| `apply.no_proposal.detail` | `Make one with:  python -m tools.learn propose` |
| `apply.malformed` | `::error::The proposal at {path} could not be read: {detail}` |
| `apply.malformed.detail` | `Nothing was applied. Re-run propose.` |
| `apply.stale.head` | `{n} edit(s) are out of date — their target file changed since the proposal was made:` |
| `apply.stale.item` | `  {file}: {instruction}` |
| `apply.stale.note` | `They are excluded from this review. Re-run propose to regenerate them.` |
| `apply.stale.all` | `Every edit in this proposal is out of date. Nothing to review. Re-run propose.` |
| `apply.no_tty` | `::error::Refusing: an edit to an agent definition is only ever applied by a person at a terminal.` |
| `apply.no_tty.detail` | `stdin or stdout is not a terminal. There is no flag that overrides this.` |
| `apply.unwritable` | `::error::Cannot write to {file}: permission denied. Fix that before reviewing.` |

---

## S6 — the review card

| Key | String |
| --- | ------ |
| `card.header` | `── edit {i} of {n} ──  {file}` |
| `card.instruction` | `  Instruction   "{instruction}"  (line {line})` |
| `card.gap` | `  Gap           {gap}` |
| `card.reproposal` | `  Re-proposal   You rejected this on {date}. {n} of the sessions below are newer than that.` |
| `card.evidence.head` | `  Evidence      {n} session(s)` |
| `card.evidence.item` | `    [{i}] {date}  session {session}` |
| `card.evidence.quote` | `        > {line}` |
| `card.evidence.path` | `        {path}` |
| `card.evidence.truncated` | `        … ({n} more line(s) — press v)` |
| `card.diff.head` | `  Proposed diff  {hunks} hunk(s), +{added} -{removed}` |
| `card.eval.covered` | `  Eval coverage  covered by {case}` |
| `card.eval.none` | `  Eval coverage  none — no eval case exercises this behaviour` |
| `card.unappliable` | `  Proposed diff  cannot be applied — {file} has changed since this was proposed` |
| `card.prompt` | `  [a]ccept  [r]eject  [s]kip  [v]iew full evidence  [?] help  [q]uit  > ` |
| `card.prompt.limited` | `  [s]kip  [q]uit  > ` |
| `card.invalid` | `  Not a choice. a accept · r reject · s skip · v view · ? help · q quit` |
| `card.help` | `  a  write this edit if you confirm at the end` |
| | `  r  reject it — it will not be proposed again unless a new session supplies fresh evidence` |
| | `  s  skip — no decision recorded; it will be proposed again next run` |
| | `  v  print the full evidence for this edit, untruncated` |
| | `  q  abandon the review — nothing written, nothing recorded` |
| `card.echo.accept` | `  → accepted` |
| `card.echo.reject` | `  → rejected` |
| `card.echo.skip` | `  → skipped` |

---

## S7 — summary, confirmation, result

| Key | String |
| --- | ------ |
| `summary.head` | `── review complete ──` |
| `summary.accepted.head` | `Accepted {n}:` |
| `summary.accepted.item` | `  {file}  {instruction}  +{added} -{removed}` |
| `summary.counts` | `Rejected {r}. Skipped {s}.` |
| `summary.skipped.note` | `Skipped edits will be proposed again on the next run.` |
| `summary.rejected.note` | `Rejected edits will not return without new evidence.` |
| `summary.none` | `Nothing accepted. {r} rejected, {s} skipped. No file was changed.` |
| `summary.none.recorded` | `The {r} rejection(s) are recorded.` |
| `confirm.prompt` | `Write {n} edit(s) to {f} file(s)? [y/N] ` |
| `confirm.files` | `  {file}` |
| `confirm.declined` | `Nothing written. No rejections recorded. The proposal is unchanged and can be reviewed again.` |
| `write.item` | `  wrote {file}  +{added} -{removed}` |
| `write.done` | `{n} edit(s) written to {f} file(s). Nothing was committed or staged.` |
| `write.review` | `Review them with:  git diff` |
| `write.undo` | `Undo them with:  git checkout -- .claude/agents/` |
| `write.evals` | `{n} accepted edit(s) change behaviour no eval covers. Recorded in {path} for TF-016.` |
| `write.honest` | `These edits are proposed on evidence. Whether they improve the team is not measurable yet.` |
| `write.failed` | `::error::Failed writing {file}: {detail}` |
| `write.failed.detail` | `Wrote {done} of {n} edit(s) before stopping. git diff is the authority on what changed — no rollback was attempted.` |
| `abort` | `Abandoned. Nothing written, nothing recorded. The proposal is unchanged.` |

---

## Strings that must not exist

Listed so they are not written by reflex:

- Any variant of "successfully improved", "the team is now better", or a claim
  that an accepted edit helped. The spec's Outcome forbids it: the honest claim
  is *proposed on evidence*. `write.honest` is the sanctioned form.
- A bare exception class, error code or traceback as the whole message. Every
  `{detail}` is a sentence fragment a person can act on, and the underlying
  exception goes to a log, not to the prompt.
- "Are you sure?" without naming what will change. `confirm.prompt` names the
  counts and lists the files.
- Any suggestion that a dead-rule candidate *should* be removed. The tool
  reports the measurement; the judgement is the CPO's.
- `--yes`, `--force`, `--non-interactive`, or any copy that mentions one. They
  do not exist (see `components.md`).
