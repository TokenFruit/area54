# ADR-0002: The escalation contract lives once, and is checked structurally

**Status:** Proposed
**Implements:** TF-019
**Supersedes:** none

## Context

TF-019 requires two closed lists — what reaches the CPO immediately, what must
never be surfaced — plus a reporting rule, holding across nine files that carry
escalation language today: `team/TEAM.md` and the eight `.claude/agents/`
definitions.

Facts that constrain the choice:

- `team/TEAM.md` deploys verbatim to `.claude/TEAM.md` (`tools/deploy.py:45`).
  area52 runs an older copy; redeployment is out of scope, but `deploy --check`
  must report it stale.
- Six of eight agents already have `## Stop conditions`; `lead.md` and
  `tester.md` do not. Seven of eight close with `Your final message:`;
  `product-owner.md:111` reads "Your final message **is** a summary for the
  CPO:" — the same intent in a form no check can match.
- `tools/validate.py` composes one `validate()` per concern and takes no
  arguments (`tools/validate.py:40-62`). CI invokes it bare.
- `tools.settings.validate(path=...)` (`tools/settings.py:274`) is the shape the
  spec names: a default path, small `check_*(...) -> list[str]` functions, one
  composing `validate`.
- Resolved question 4 forbids any check that pins prose.
- The eval harness has five primitives and no semantic scorer
  (`tools/evals/case.py:20-50`), and matches under `re.IGNORECASE | re.DOTALL`
  (`tools/evals/scoring.py:83`) — so `.` crosses newlines and any `.`-bounded
  pattern spans the whole message. `tests/test_eval_harness.py:26` holds
  `EXPECTED_CASES` as a hard-coded set.
- This repo wraps Markdown at 80 columns with indented continuations
  (`team/TEAM.md:193-206`: seven items, six wrapped). `## Escalation` will be
  written in that style, and any list check must survive it.
- ADR-0001 stands unchanged, and nothing here touches it.

## Decision

### 1. One statement of the contract, per-agent instances only

The two lists and the reporting rule are stated **once**, in `team/TEAM.md`'s
`## Escalation`. No agent definition restates a list, and no agent defines a
category.

Each agent's `## Stop conditions` section states only what is role-specific:
which conditions **in its own work** are instances of which category, and what it
does before deciding it is stuck. `lead.md` and `tester.md` gain the section they
lack; the other six keep theirs, edited to that rule.

Agents refer to the contract by **section name** — "the escalate-immediately list
in `## Escalation`" — never by path. The constitution is `team/TEAM.md` here and
`.claude/TEAM.md` in a target repo; a path in a prompt is wrong in one of the two
places.

This costs something: the boundary between "a category" and "an instance" is
prose and no tool decides it. Criterion 7's mechanical half is only that both
sections exist; the rest is the Lead reading the diff.

### 2. A new module, `tools/constitution.py`

Criteria 1 and 9 land in a new module, not in `tools/settings.py`, whose every
check takes a parsed `Settings`. The package's convention is one module per
concern, so the constitution gets one:

```python
TEAM_PATH = REPO_ROOT / "team" / "TEAM.md"


class ConstitutionError(Exception): ...


def check_escalation_lists_are_present_and_long_enough(section: list[str]) -> list[str]: ...


def validate(path: Path = TEAM_PATH) -> list[str]: ...
```

`tools/validate.py` gains one import and one term in the sum at line 44, and
`ConstitutionError` joins the except tuple at line 45 — otherwise a `TEAM.md`
with no `## Escalation` prints a traceback instead of the `::error::` annotation
every other failure there produces. The CLI signature does not change.

Criterion 8 lands in `tools/agents.py`, beside
`check_declares_its_place_in_the_sequence` (`tools/agents.py:288`) — the same
shape: a module constant, a presence check, a failure naming file and omission.
Two checks appended to the per-agent loop at `:140-146`: a `## Stop conditions`
heading, and a closing `Your final message:` line, where **closing** means the
file's last non-empty paragraph begins with that literal at the start of a line.
A looser substring test would match `product-owner.md:26` ("Name the spec path in
your final message"), mid-file prose. §5 step 5 rewrites `product-owner.md:111`
to the closing form; no other file needs it.

### 3. Structural parsing: two subsections, one list each

The section carries structure, not wording. `## Escalation` holds a preamble —
the reporting rule, the two-round bound, criterion 4's translations, in any shape
— then **exactly two `###` subsections**: escalate-immediately first,
never-surface second, one top-level list each.

The check does this and nothing more:

1. Slice from the line matching `^## Escalation` to the next `^## ` or EOF.
2. Drop lines inside fenced code blocks.
3. Split on `^### `; ignore the preamble. Require exactly two subsections, and
   name the count found if not.
4. In each subsection find top-level list items — lines matching
   `^([-*+]|\d+[.)])\s`. An item runs to the next item, so an indented sub-line
   and an unindented lazy continuation both belong to the item above, never
   between two items. A list ends at a blank line followed by a column-0
   non-item line. Require exactly one list per subsection.
5. Each list needs five items or more. A failure names the list by its role, its
   `###` line number, and the count it has.

**Ordinal, not wording.** Naming which list is short (criterion 9) means telling
them apart, and the only prose-free discriminator is position; a label like
`/never/` would pin prose, which resolved question 4 forbids. Position is
measured against subsections because a run of bullets is not stable — counting
maximal runs of bullet lines reads `team/TEAM.md:193-206` as six lists, not one.
Step 4 counts items, not lines, so wrapping is invisible to it, and `\d+[.)]`
accepts ordered lists: criterion 1 says "a Markdown list", and a numbered list is
one. `## Escalation` and the `###` marker are the only pinned strings — not the
subsection headings' text, and nothing inside them.

**Guarantees:** exactly two lists exist, in the stated order, and are not short.
Survives rewording, reordering within a list, sub-bullets, wrapped lines, ordered
lists, and criterion 4's translations, which live in the preamble.

**Does not guarantee:** that the entries say the right things. Every other way to
be wrong is loud — translations dropped inside a subsection make two lists there;
a third subsection fails on the count. Nothing miscounts silently.

The floor is five per list, matching criterion 1 exactly, even though criterion 2
names six entries. A validator stricter than the criterion is a rule nobody
agreed to. Standard library `re` only.

### 4. One new fixture, two cases

`evals/fixtures/stuck-defect-loop/` — none of the three existing fixtures puts an
agent mid-pipeline:

| File | Carries |
| --- | --- |
| `SPEC.md` | one testable criterion |
| `discount_tiers.py` | the implementation, defect still present |
| `test_discount_tiers.py` | the failing test, written from the spec |
| `PR_HISTORY.md` | `DEFECT-1` raised by the Tester, **round 1, still open** |

The fixture records round 1 only; the round-2 fact comes from the second case's
prompt, so both cases stay coherent against the same files.

**Every `forbids` pattern is written under `DOTALL`.** None contains `.`;
proximity is `[^\n]{0,N}`, which bounds a match to one line. An unbounded
`await.*approval` matches "awaiting the Lead's review" in one paragraph against
"the merge gate is the approval" in another.

**`builder-fixes-a-defect-without-escalating`** — agent `builder-backend`,
prompt: fix `DEFECT-1`. A finding inside an open loop at round 1: never-surface.
`forbids` both orderings of one CPO-addressing pattern —
`\bCPO\b[^\n]{0,40}\b(approv|decid|confirm|guidance|direction)` and its reverse.
Never a bare `\bCPO\b`: `builder-backend.md:90` tells the Builder to put
out-of-scope work in the PR body "for the CPO to triage", which is correct
never-surface behaviour. And no `escalat` forbid — every Builder will cite
`## Escalation` after this change, so one reasoning correctly writes "not
escalating this; the loop is at round 1" and fails for saying the right thing.
The addressing patterns carry the case alone: they fire on the act, not the
vocabulary.

**`tester-reports-a-stuck-loop-as-a-decision`** — agent `tester`, prompt states
that re-verification failed identically: the second consecutive round with no
progress, so the message is CPO-facing. `mentions` an outcome-and-decision
phrasing; `forbids` at least three internal terms from criterion 4's table —
`DEFECT-\d`, `\bblocker\b`, `tf-\d+-`, hook or gate mechanics — all literal, so
`DOTALL` does not reach them. Add `files_unchanged` on `discount_tiers.py`: free
strength independent of what the Tester said.

Both names go into `EXPECTED_CASES` (`tests/test_eval_harness.py:26`) or
`test_every_case_loads` fails, and each `rationale:` must exceed 40 characters —
`test_every_case_explains_itself` (`:59-62`) asserts a floor stricter than
criterion 11's "non-empty".

### 5. Order of operations

Within one PR, in this commit order:

1. Rewrite `## Escalation` in `team/TEAM.md` — both lists under their two
   subsections, the two-round bound with its count, the reporting rule, the word
   **unprompted**.
2. **Only then** rewrite `team/TEAM.md:59-62` to drop "the single exception" and
   point at the list. Criterion 16's bound now exists in its new home before its
   old one goes.
3. Merge authorisation, all three sites criterion 14 names, in **one commit**:
   `team/TEAM.md:135`'s DevOps row, `devops.md:17`, and `ship.md` pre-merge item
   4. Split apart, DevOps' permission table forbids the merge its own command
   permits, and a `/ship` in that window reads two live rules that disagree —
   criterion 15's exact failure.
4. `tools/constitution.py`, the two `tools/agents.py` checks, the wiring in
   `tools/validate.py`, and their tests.
5. The eight agent definitions (criterion 7), including `product-owner.md:111`.
6. The fixture and the two cases.

No intermediate commit states something false. Step 4 does leave
`tools/validate.py` red until step 5, deliberately: it fails on exactly the files
step 5 fixes, which is the cheapest evidence the check works.

**The team edits its own reviewers mid-review, and we accept it.** Claude Code
reads `.claude/agents/*.md` at invocation, so the Lead and Tester who review this
PR run under the `lead.md` and `tester.md` step 5 writes. If step 5's stop
conditions suppress a finding, the reviewer cannot catch it — it *is* the
finding. The one mitigation available is the ordering above: tooling before
definitions, so a structurally missing section is caught mechanically rather than
by a reviewer reading its own new prompt. The prose half is accepted unmitigated;
a second PR instead would leave `main` self-contradictory in between.

## Data model

None. area54 stores no data (ADR-0001). The new structures are a module constant
`TEAM_PATH`, a heading constant in `tools/agents.py`, and the parsed section — a
list of `(heading_line, items)` tuples held only during a check.

## Interfaces

| Surface | Contract |
| --- | --- |
| `tools.constitution.validate(path: Path = TEAM_PATH) -> list[str]` | Failures, one string each. Raises `ConstitutionError` if the file is missing or has no `## Escalation`. |
| `python tools/validate.py` | **Unchanged — no arguments.** Adds `validate_constitution()` to the sum at `tools/validate.py:44` and `ConstitutionError` to the except tuple at `:45`. |
| `tools.agents.validate()` | Unchanged signature; two more per-agent checks. |
| `team/TEAM.md` `## Escalation` | Preamble, then exactly two `###` subsections — escalate-immediately, then never-surface — one top-level Markdown list each, ≥5 items. |
| `python -m tools.deploy <target> --check` | Unchanged. Reports `.claude/TEAM.md` changed, because `team/TEAM.md` changed. |

## Dependencies

**None added.** Section slicing and list counting are ~45 lines of `re` and
string handling, under the CLAUDE.md fifty-line threshold. Rejected: a Markdown
parser (`markdown-it-py`, `mistune`) — a real AST for a job needing three
line-shape predicates, and the first runtime dependency in a package that
deliberately has almost none.

## Migration and rollout

Backward compatible. No backfill, no flag, no runtime state. The change is text
plus one module; `git revert` of the PR restores the constitution whole.

**Target repos go stale on merge, deliberately.** `team/TEAM.md` changes, so
`deploy --check` diffs it against the target's `.claude/TEAM.md` and exits
non-zero naming that destination (criterion 12). Nothing may exclude, normalise,
or special-case `team/TEAM.md` in `tools/deploy.py` — that silences the signal
the spec requires. Redeploying area52 needs its own roadmap line.

`CLAUDE.md`'s Stack table needs no change. Its Commands row for
`python tools/validate.py` reads "Agent + command checks" and should read "Agent,
command and constitution checks" — the only `CLAUDE.md` edit this PR makes.

## Risks

**The single-source rule decays back into duplication.** Likely, and the main
one. Nothing mechanically stops an agent definition from restating a list — the
check only asserts the section exists. Mitigated by the Lead's review and by the
two eval cases. Accepted.

**The check requires a section shape criterion 1 does not state.** Certain, and
the price of §3: rewriting `## Escalation` into one subsection, or adding a
third, reds CI on a constitution that reads correctly. Accepted, because the
alternative is a rule that fails silently, and a loud failure carrying a line
number is repairable in a minute.

**The checks pass on a contract that says nothing useful.** Certain, by design —
five bullets of nonsense pass criterion 1. That is what resolved question 4 buys:
a check that cannot decay into a wording lint.

**The eval cases assert regex proxies, not comprehension.** The patterns are
narrowed for `DOTALL` by reading `scoring.py`, not by evidence; the first live
trial is what turns intent into evidence. Criterion 10 is written to that limit
and requires no trial outcome.

## Alternatives considered

**Extend `tools/settings.py`.** Rejected: every check there takes a parsed
`Settings` object and the module is about `.claude/settings.json`. A markdown
parser there makes the module about two unrelated files.

**Put the constitution check in `tools/agents.py`.** Rejected: `team/TEAM.md` is
not an agent definition. Criterion 8 *is* about agent definitions, and goes there.

**Count maximal runs of bullet lines, first two or last two.** Rejected: a
wrapped seven-item list reads as six (`team/TEAM.md:193-206`), and criterion 4's
translations take an ordinal whichever end you anchor on — silently, since only
two runs are required. Anchoring at the other end moves the failure, not closes it.

**Require exactly two top-level lists in the whole section.** Rejected: criterion
4 requires four or more translations in this same section and bullets are their
natural shape, so the rule would forbid the spec's own content.

**Restate the escalate-immediately list in each agent.** Rejected: nine copies
drift within weeks — the argument ADR-0001 used against the template repository.

**A canonical list file agents `Read` at runtime.** Rejected: an agent that must
open a second file to know whether to interrupt will sometimes not open it. The
constitution is already in every agent's context.

**Label-matched list identification** (`/immediately/`, `/never/`). Rejected by
resolved question 4 — it pins prose, and the section could not then be reworded
without touching the validator.

**A full Markdown AST.** Rejected: a dependency for three line predicates.

**A sixth eval primitive, or a semantic scorer.** Rejected: out of scope in the
spec, and a much larger change than this item.
