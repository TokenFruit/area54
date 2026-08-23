# TF-020 — states

**This is the file to build from.** Seven surfaces, every state of each. Exact
wording lives in `copy.md`; this file says what appears, when, and why.

A surface that ships only its populated state is incomplete
(`docs/design/README.md`), and that applies to a terminal exactly as it applies
to a screen — a CLI that prints nothing on an empty corpus has an unspecified
empty state, not no empty state.

---

## Global rules

**Width.** Everything must be legible at 80 columns and must not assume more.
Wrap prose at 79. Never wrap a diff line or a path — let the terminal do it, so
a copied path stays one token.

**Colour is never the only carrier.** Diff lines lead with `+` / `-`; check
lines lead with `[PASS]` / `[FAIL]` (the `tools/merge_gate.py` convention);
warnings lead with the word. Honour `NO_COLOR` and any non-TTY stdout by
dropping colour entirely, and the output must lose no meaning when it does.

**Screen readers.** No box-drawing for structure that carries meaning; the
`── name ──` rule from `tools/telemetry.py:129` is decoration only. No spinner
glyph animation — progress is one appended line per completed unit, which reads
correctly when spoken and when piped to a file.

**Latency.** Anything over ~300 ms prints a line before it starts and a line
when it finishes. The two model steps are the only slow things here.

**Nothing is cleared.** No alternate screen buffer, no cursor games beyond
overwriting the current progress line. The CPO must be able to scroll back
through the evidence he just accepted on.

**Exit codes.** `0` a complete run, including "nothing to propose". Non-zero for
a refusal, a breached ceiling, a failed gate, a broken store, or an aborted
write. "Nothing found" is not a failure; "could not look" is.

---

## S1 — `propose`, run progress

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty** | No progress phase at all. Collection reports zero sessions and the run ends at S2's empty state. Never a progress bar over zero items. |
| **Loading** | **Blocking — this is the whole command.** Per phase, a headline naming the phase and its unit count. The analyse phase prints one line per transcript as it *completes*: index, total, session id short form, elapsed, and **running spend**. Spend is visible from the first completed call, not only at the end, so a run heading for the ceiling can be interrupted by hand. Phases that finish under ~300 ms print only their result line. |
| **Populated** | The phases in order, each with its counts: collected, distilled, analysed, aggregated, synthesised, gated. |
| **Partial** | The norm, not the exception. Skipped transcripts are counted inline as they are skipped, with the reason class, and re-stated in S2. A phase that lost items still prints its own success line — `analysed 11 of 14` — never a bare `analysed 11`, so the denominator is always present. |
| **Error** | The failing phase's line is completed with the failure, in plain words, and the run stops there. Nothing downstream prints a phase headline it never entered. Ceiling breach stops mid-phase and says how far it got and what it spent. |
| **Permission denied** | The transcript store is unreadable (POSIX permissions, or a sandbox). Named as a permission problem against a path, distinguished from "not found", and exits non-zero without a model call. |
| **Offline** | Collection, distillation and redaction are local and complete normally. The first model call fails. The message says the local work is done, that no proposal can be made without the model, and that re-running repeats only the cheap local phases. No retry storm: fail on the first call, not the fourteenth. |

---

## S2 — `propose`, the run report

Printed after progress, on every terminating path except a permission or store
failure. Sections in this order: corpus, discarded, sightings, proposal,
relevance (S3), spend.

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty — no sessions** | One sentence: nothing for this repo in the store. Then where it looked and how many sessions it saw belonging to *other* directories, so "empty" is distinguishable from "looked in the wrong place". No proposal. Exit 0. |
| **Empty — nothing new** | Sessions analysed, no gap has reached two independent sightings. The sighting table prints anyway, showing each held gap at `1 of 2`, so he can see what is pending. No proposal. Exit 0. |
| **Empty — all suppressed** | Every candidate gap was previously rejected and has no new evidence. Says how many, and that they are suppressed by earlier rejections rather than absent. No proposal. Exit 0. |
| **Loading** | n/a — S1 owns the wait; the report is composed and printed at once. |
| **Populated** | Corpus counts (found / in-repo / self-excluded / skipped); claims discarded for non-verbatim quotes; sightings promoted this run; **N proposed edits, of which M re-proposals**; then S3; then spend against ceiling; then the proposal path and the exact `apply` command to run next. |
| **Partial** | Some transcripts skipped, or one analysis call failed while others succeeded. The report states the corpus it actually reasoned over, as `analysed N of M`, and **names every skipped transcript with its reason class** — unparseable, unredactable, self-excluded, out of repo. A proposal built on a partial corpus says so on its own line, above the edits. |
| **Error — ceiling breached** | Names the breach: proposed count versus ceiling. States that no proposal was written, and that it did **not** truncate to the cap. Names `--max-edits` as the way to raise it deliberately. Exit non-zero. |
| **Error — gate disagreement** | Names both sides: the measured change with no proposed edit, or the proposed edit with no measured change, and the file each is in. No proposal written. Exit non-zero. |
| **Error — out-of-scope path** | Names the staged path and states that only `.claude/agents/` may be edited. No proposal written. Exit non-zero. |
| **Permission denied** | See S1. Reported instead of, not alongside, the report body. |
| **Offline** | The corpus section still prints, because collection succeeded. Then the model failure. No proposal. |

---

## S3 — relevance and dead-rule candidates

A section of S2, one block per agent definition.

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty — too few sessions** | Suppressed with a reason: a citation share over fewer than two analysed sessions is noise. Says how many sessions it had. |
| **Empty — no dead candidates** | The per-instruction shares still print; a line confirms every instruction was cited at least once. This is a good result and reads as one. |
| **Loading** | n/a — derived from data already in hand. |
| **Populated** | Per agent: each instruction (short label plus the file line reference), and the share of analysed sessions citing it, as `k/N`. Sorted ascending so the least-cited are read first. Dead-rule candidates listed under their own heading. |
| **Partial** | Only the agents that appeared in the corpus are scored. Agents with no session in this corpus are listed by name as **unmeasured**, explicitly not as dead — the difference matters and colour must not be what carries it. |
| **Error** | If citation matching failed for an agent, that agent's block says so and is omitted from the candidate list rather than defaulting to "all dead". A failure to measure never manufactures a deletion. |
| **Permission denied** | n/a — reads files already read. |
| **Offline** | n/a — no network. |

---

## S4 — the proposal file

A gitignored artefact under the tool's state directory. It is the durable form
of what S2 announced and what S6 will render, and the CPO may read it directly
in an editor.

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty** | The file is not written at all when there is nothing to propose. **No empty proposal file**, so its presence always means there is a decision waiting. |
| **Loading** | n/a — written atomically at the end of a run. |
| **Populated** | Run metadata (when, corpus size, ceiling, spend), then per edit: target file, instruction, gap, verbatim quotes with session id, date and raw path, unified diff hunks, eval-coverage note, re-proposal marker. Human-readable as text without a renderer. |
| **Partial** | Carries the same partial-corpus banner S2 printed, so a proposal read three days later still discloses that it saw 11 of 14 sessions. |
| **Error** | Unreadable or malformed at `apply` time: `apply` refuses it by name rather than applying whatever parsed, and says to re-run `propose`. |
| **Permission denied** | State directory not writable: `propose` fails at the end naming the path, and **says the analysis is lost and the spend with it** — this is the one failure that costs money to retry, so it is stated bluntly. |
| **Offline** | n/a — local file. |

---

## S5 — `apply`, preamble

Printed once, before the first card.

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty** | No proposal file: one sentence saying so, plus the `propose` command to make one. Exit non-zero — he asked to apply something that does not exist. |
| **Loading** | Parsing a proposal is fast; no phase line unless it exceeds ~300 ms. |
| **Populated** | Proposal age, the corpus it came from, how many edits and across how many files, how many are re-proposals, and the key legend. Then the first card. The legend prints **before** the first prompt, never only in `?`. |
| **Partial** | Some edits are stale — the target file changed since `propose` ran. Those are named up front, counted, and excluded from the loop; the rest proceed. A stale-hunk-only proposal falls through to the empty state with the staleness as its reason. |
| **Error** | Malformed proposal: refuse by name, exit non-zero, do not partially apply. |
| **Permission denied — no TTY** | **The defining state of this surface.** Piped stdin, CI, a subagent shell: one sentence saying an edit to an agent definition is only ever applied by a person at a terminal, and that there is no flag to override. Exit non-zero. Nothing else prints — no edit list, no diff — so a non-interactive caller cannot even use `apply` to dump the proposal. |
| **Permission denied — unwritable target** | Detected before the loop, not after his decisions. Names the file, exits non-zero, and does not waste his review. |
| **Offline** | Fully functional. `apply` makes no network call, and that is a property worth relying on. |

---

## S6 — `apply`, the per-edit review card

The core surface. Order is fixed: **evidence before diff** (see `flows.md`).

```
── edit 2 of 4 ──────────────────────────────  .claude/agents/tester.md

  Instruction   "Run the full regression suite before reporting"  (line 34)
  Gap           Tester reported a verdict without running the suite.

  Evidence      2 sessions

    [1] 2026-08-11  session 4f2a1c8e
        > I'll take the unit tests as sufficient here and report Pass.
        ~/.claude/projects/-Users-…-area-54/4f2a1c8e-….jsonl

    [2] 2026-08-19  session 9b70d114
        > Regression suite skipped — the diff is small.
        ~/.claude/projects/-Users-…-area-54/9b70d114-….jsonl

  Proposed diff  1 hunk, +3 -1

    @@ -32,7 +32,9 @@
    -  Run the full regression suite before reporting.
    +  Run the full regression suite before reporting. A verdict reported
    +  without a completed suite run is not a verdict; say so and stop.
    +  "The diff is small" is not an exemption.

  Eval coverage  none — no eval case exercises this behaviour

  [a]ccept  [r]eject  [s]kip  [v]iew full evidence  [?] help  [q]uit  >
```

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty** | Unreachable — a card exists only because an edit does. An edit that reaches the loop with zero evidence quotes is a **bug in the gate, not a state**: fail the run loudly at S2 rather than render an evidence-free card. |
| **Loading** | n/a — everything is in the proposal file. No card ever waits on I/O. |
| **Populated** | As above. |
| **Partial — truncated evidence** | Long quotes are truncated to a stated line count with `… (N more lines — press v)`. The count is always shown; a quote is never silently shortened, because the CPO is being asked to trust that these words are verbatim. `v` prints the untruncated evidence and re-prompts without consuming a decision. |
| **Partial — re-proposal** | An extra line above the evidence: rejected before, on what date, and that the evidence below includes at least one session newer than that rejection. Marked by the word, not by colour. |
| **Error — invalid keypress** | Restate the legend in one line and re-prompt. **No default action.** Enter alone re-prompts. Ctrl-C behaves as `q`: nothing written, nothing remembered. |
| **Error — hunk no longer applies** | Should be caught at S5; if it surfaces here, the card renders with the diff replaced by a one-line explanation and offers only `s` and `q`. Never offer `a` on a hunk that cannot be applied. |
| **Permission denied** | n/a at card level — checked at S5. |
| **Offline** | Fully functional. |

**Responsive.** At ≥100 columns the layout above is used as written. Under 80,
labels move onto their own line above their value and quotes are indented two
spaces instead of eight; nothing is dropped, nothing is horizontally scrolled.
Diff and path lines are never re-wrapped by the tool at any width.

---

## S7 — `apply`, summary, confirmation and result

| State | What the CPO sees |
| ----- | ----------------- |
| **Empty — nothing accepted** | All edits rejected or skipped: counts, no confirmation prompt, no write, exit 0. Rejections **are** recorded — a review completed with all-reject is a real decision, not a no-op. |
| **Loading** | The write itself is milliseconds. No progress. |
| **Populated** | A recap: each accepted edit as one line (file, instruction, `+a -b`), the reject and skip counts, then a single `y/N` confirmation naming the files that are about to change. **Default is No.** On `y`: files written, one line each, then the closing note — uncommitted, `git diff` to review, `git checkout` to undo. |
| **Partial** | Accepted, rejected and skipped in the same run: all three counts, and what each means for next time — accepted are on disk, rejected will not return without new evidence, **skipped will be proposed again**. |
| **Error — declined at confirmation** | Nothing written, no rejections recorded, proposal intact and re-runnable. Says all four of those things, because "nothing happened" is otherwise indistinguishable from a crash. |
| **Error — write failed partway** | Stop at the first failure. Name what was written and what was not, exit non-zero, and point at `git diff` as the authority over the tool's own account of itself. Do not attempt an automatic rollback over files the CPO may already have open. |
| **Permission denied** | Pre-checked at S5; if it still fires here it is the partial-write error above. |
| **Offline** | Fully functional. |

**Destructive-action rule.** Writing to an agent definition is the one
destructive act in this feature. It is confirmed twice — once per edit, once in
aggregate — and reversible, because the tool never commits and never stages.
That is deliberate: `git` is the undo, and the closing copy names it.
