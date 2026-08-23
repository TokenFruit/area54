# TF-020 — flows

The whole feature is two commands run by one person, the CPO, at a terminal in
this repo. Names below are provisional; **ADR-0003 owns them** (see `README.md`).

```
python -m tools.learn propose [REPO] [--max-edits N] [--budget USD]
python -m tools.learn apply   [--proposal PATH]
```

They are separate commands on purpose (resolved question 1, propose/apply
separation): `propose` spends money and touches no agent definition; `apply`
spends nothing, needs no network, and is the only thing that writes.

---

## Story 1 — "a repeated failure arrives as a proposed edit with its evidence"

### Entry

The CPO decides to run the loop. Nothing schedules it (out of scope: "Running
this automatically"). He types `propose`.

### Steps

1. **Collect.** Sessions are located in the transcript store and filtered to
   this repo by resolved `cwd`. The tool's own prior sessions are excluded.
   → the run states found / skipped / self-excluded counts *before* spending
   anything.
2. **Distil and redact.** Each transcript is reduced and secret-shaped values
   removed. **No model call has been made yet** (criterion 3). A transcript that
   cannot be parsed or redacted is skipped here, named, and never sent.
3. **Analyse.** One cheap-model call per distilled transcript. This is the long
   step and the bulk of the spend, so it is the step that carries progress.
4. **Aggregate.** Claims whose quotes are not verbatim in their cited transcript
   are discarded; the count is reported. Surviving gaps are matched against the
   ledger: a gap seen in one session only is held, not proposed.
5. **Synthesise.** One strong-model call, editing a staging copy of
   `.claude/agents/`.
6. **Gate.** Staging diff versus proposed hunks must agree; no staged path
   outside `.claude/agents/`; edit count within the ceiling.
7. **Report and write the proposal.** The report ends with what the run actually
   spent, and the path to the proposal file.

### Decision branches

| At | Condition | Branch |
| -- | --------- | ------ |
| 1 | no sessions for this repo | report plainly, exit 0, write no proposal |
| 1 | store missing or unrecognised shape | report plainly, exit non-zero, no model call |
| 2 | a transcript cannot be parsed or redacted | skip **that** transcript, name it, continue with the rest; if none survive, treat as "no sessions" |
| 3 | cost ceiling reached mid-run | stop, report spend and how far it got, write no proposal, exit non-zero |
| 4 | every surviving gap has one sighting only | report "nothing new yet", record the sightings, write no proposal, exit 0 |
| 4 | a gap is on the rejection list and no new evidence | drop it silently from the proposal, count it in the report line for suppressed-by-rejection |
| 4 | a gap is on the rejection list **with** new evidence | include it, **marked a re-proposal** (criterion 12) |
| 6 | more edits than the ceiling | **fail loudly, write nothing** — never truncate to the cap (criterion 7) |
| 6 | staging diff and hunks disagree | fail, name both sides, write nothing |
| 6 | a staged path outside `.claude/agents/` | fail, name the path, write nothing |

### Exit

A proposal file on disk and its path printed, or a stated reason there is none.
**In every branch, `.claude/agents/` is byte-identical to before** (criterion 8).

### Where the CPO gets stuck, and the way out

- *"It ran for four minutes and I don't know if it's alive."* — step 3 emits one
  line per transcript as it completes, with a running count and running spend.
  Nothing over ~300 ms is silent.
- *"It failed the ceiling and I want the proposal anyway."* — he cannot have it;
  that is the criterion. The failure message names the flag (`--max-edits`) that
  raises the ceiling and re-runs, rather than leaving him to find it.
- *"It said nothing new. Did it work?"* — the "nothing new" report still prints
  the sighting table, so a gap at one-of-two is visibly *pending*, not absent.

---

## Story 2 — "a rule no session has needed is named as dead"

Not a separate command. The relevance table is a section of the same `propose`
report (criterion 13), because a dead-rule candidate is only meaningful next to
the session count it was measured over.

### Steps

Per agent definition: each instruction, and the share of analysed sessions that
cited it. Instructions cited in none are listed as **dead-rule candidates**.

### Branches

- The synthesis step may propose a **removal** for a candidate. It then appears
  in the review loop as an ordinary edit and passes the same evidence and
  staging gates — there is no shortcut path for deletions.
- A candidate with **no** removal proposed is still printed. It is information,
  not an action, and the report says which it is so the CPO does not go hunting
  for an edit that was never made.
- Fewer than the two-session floor of analysed sessions: the table is suppressed
  with a reason, because "cited in 0 of 1 sessions" is noise, not a dead rule.

### Exit

The CPO either accepts a proposed removal in `apply`, or notes a candidate and
does nothing. Doing nothing is a valid, expected outcome and the copy does not
nag about it.

---

## Story 3 — "nothing edits an agent definition unattended"

### Entry

`apply`, with a proposal on disk.

### The gate before the flow

`apply` checks for an attached terminal on **stdin and stdout** before anything
else. Piped input, CI, a subagent's shell: refuse, exit non-zero, and say why
in one sentence (criterion 11). No `--yes`, no `--force`, no environment
variable defeats this. There is no non-interactive path to a write, so there is
nothing for a persuasive prompt to find.

### Steps — the review loop

Preamble, then one **review card** per edit, then a confirmation.

```
preamble ─→ card 1 ─→ card 2 ─→ … ─→ card N ─→ summary ─→ confirm ─→ write
                │                                              │
                └─ q (quit) ──────────────────────────────────┴─→ nothing written
```

Each card, in this order — **evidence before remedy** is the key interaction
decision of this design:

1. Which agent definition, and which instruction, this touches.
2. The gap, in one sentence.
3. **The verbatim evidence**: N quotes, each with the session id and date it
   came from, and the path to the raw transcript.
4. **The diff**, as unified hunks.
5. Whether an eval already covers the behaviour being changed (resolved
   question 8).
6. Whether this is a re-proposal, and when it was rejected before.
7. The prompt.

The CPO reads the case before he reads the remedy. A diff shown first invites a
judgement on whether the wording is nice; the evidence first asks the question
that actually matters — *did this really happen twice?*

### Keys

| Key | Meaning |
| --- | ------- |
| `a` | accept this edit |
| `r` | reject it — recorded, and not re-proposed without new evidence |
| `s` | skip — decide next run; neither written nor remembered |
| `v` | print the full evidence for this edit, untruncated, then re-prompt |
| `?` | key help, then re-prompt |
| `q` | quit the whole review; **nothing is written, nothing is remembered** |

Every key has a spelled-out long form (`accept`, `reject`, …). Enter alone
re-prompts; it never picks a default. There is no default action on an
ambiguous keypress — an accidental Return must not edit an agent definition.

### Decision branches

| Condition | Branch |
| --------- | ------ |
| no proposal file | say so, name the command that makes one, exit non-zero |
| proposal exists but every edit already decided | say so, exit 0 |
| proposal is stale — an agent file changed since `propose` ran | refuse the affected edits by name, offer the rest; a hunk that no longer applies is never force-fitted |
| all edits rejected or skipped | no confirmation prompt, no write, report the counts |
| ≥1 accepted | summary, then a single **y/N** confirmation naming the files and hunk counts |
| confirmation declined | nothing written, decisions discarded, proposal intact |
| `q` at any card | nothing written, decisions discarded, proposal intact |
| a write fails partway | stop, name what was written and what was not, exit non-zero, tell him `git diff` is the truth |

### Exit

Accepted hunks are in `.claude/agents/*.md`, **uncommitted**. Rejections are in
the rejection memory. The closing line says what changed and points at
`git diff` — the tool never commits, so his own review of the diff is the last
gate and the undo is `git checkout`.

---

## Story 4 — "anything secret-shaped is removed before a model sees it"

The developer whose sessions form the corpus is not at the terminal, so this
story's surface is **an assurance printed to whoever is**. Redaction is ordered
before the first model call, and the report says so in the run's own words: how
many values were redacted, and how many transcripts were withheld entirely for
failing redaction. A withheld transcript is named and its reason given; it never
becomes a silent omission from the corpus.

The distilled artifacts and cached evidence are gitignored (resolved question
5). The ledger and rejection memory hold references only. **No verbatim excerpt
is ever printed by `propose` into a log the CPO might paste** — quotes appear
only inside the interactive `apply` cards and in the gitignored proposal file.
