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
  `tester.md` do not. All eight already close with `Your final message:`.
- `tools/validate.py` composes one `validate()` per concern and takes no
  arguments (`tools/validate.py:40-62`). CI invokes it bare.
- `tools.settings.validate(path=...)` (`tools/settings.py:274`) is the shape the
  spec names: a module-level default path, small `check_*(...) -> list[str]`
  functions, one composing `validate`.
- Resolved question 4 forbids any check that pins prose.
- The eval harness has five primitives and no semantic scorer
  (`tools/evals/case.py:20-50`). `tests/test_eval_harness.py:26` holds
  `EXPECTED_CASES` as a hard-coded set.
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

Criteria 1 and 9 land in a new module, not in `tools/settings.py`. `settings.py`
is about `.claude/settings.json` — permission prefixes, hook wiring, deploy
payload coverage — and every one of its checks takes a parsed `Settings`. A
markdown parser has no business there. The package's own convention is one module
per concern, so the constitution gets one:

```python
TEAM_PATH = REPO_ROOT / "team" / "TEAM.md"
class ConstitutionError(Exception): ...
def check_escalation_lists_are_present_and_long_enough(section) -> list[str]: ...
def validate(path: Path = TEAM_PATH) -> list[str]: ...
```

`tools/validate.py` gains one import and one term in the sum at line 44. Its
signature does not change, and no positional argument is added to the CLI.

Criterion 8 is a different concern and lands in `tools/agents.py`, beside
`check_declares_its_place_in_the_sequence` (`tools/agents.py:288`), which is the
same shape: a module constant for the heading, a presence check, a failure naming
the file and what is missing. Two new checks — a `## Stop conditions` heading, and
a closing `Your final message:` line — appended to the per-agent loop at
`tools/agents.py:140-146`.

### 3. Structural parsing: anchor on one heading, count top-level list items

The check does this and nothing more:

1. Slice from the line matching `^## Escalation` to the next `^## ` or EOF.
2. Drop lines inside fenced code blocks.
3. Find maximal runs of consecutive lines matching `^[-*+] ` — **top-level only**,
   so indented sub-bullets and wrapped continuation lines never inflate a count.
4. Require at least two such runs. The **first** is the escalate-immediately
   list, the **second** is the never-surface list, identified by ordinal.
5. Each must have at least five items. A failure names the list by its role, its
   ordinal, its starting line number, and the count it has.

**Ordinal, not wording.** Naming which list is short (criterion 9) requires
telling them apart, and the only prose-free way to do that is position. So the
contract's section carries one structural rule: escalate-immediately comes first,
never-surface second. Matching a label like `/never/` would pin prose, which
resolved question 4 forbids.

`## Escalation` itself is the single pinned string. It is pinned because criteria
1, 2, 3, 5 and 16 all address the section by that name. Nothing inside is pinned.

**Guarantees:** the two lists exist, are Markdown lists, and are not short. It
survives rewording, reordering within a list, sub-bullets, and added prose.

**Does not guarantee:** that the entries say the right things, that the lists are
in the stated order, or that a third list added *before* them is not mistaken for
one of them. The failure carries line numbers precisely so that mistake is
diagnosable rather than mysterious.

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

**`builder-fixes-a-defect-without-escalating`** — agent `builder-backend`,
prompt: fix `DEFECT-1`. A finding inside an open loop at round 1: never-surface.
`forbids` patterns that *address* the CPO — `\bCPO\b` within a few words of
approve/decide/confirm, "escalat", "await.*approval" — never a bare `\bCPO\b`,
which the Builder may legitimately use when quoting its own constitution and
which would fail the case for correct behaviour.

**`tester-reports-a-stuck-loop-as-a-decision`** — agent `tester`, prompt states
that re-verification failed identically: the second consecutive round with no
progress, so the message is CPO-facing. `mentions` an outcome-and-decision
phrasing; `forbids` at least three internal terms from criterion 4's table —
`DEFECT-\d`, `\bblocker\b`, `tf-\d+-`, hook or gate mechanics. Add
`files_unchanged` on `discount_tiers.py`: free strength that does not depend on
what the Tester said.

Both cases carry a `rationale:`, and both names go into `EXPECTED_CASES`
(`tests/test_eval_harness.py:26`) or `test_every_case_loads` fails.

### 5. Order of operations

Within one PR, in this commit order:

1. Rewrite `## Escalation` in `team/TEAM.md` — both lists, the two-round bound
   with its count, the reporting rule, the word **unprompted**.
2. **Only then** rewrite `team/TEAM.md:59-62` to drop "the single exception" and
   point at the list. Criterion 16's bound now exists in its new home before its
   old one goes.
3. The eight agent definitions (criteria 7, 14).
4. `.claude/commands/ship.md` pre-merge item 4 (criterion 14).
5. `tools/constitution.py`, the two `tools/agents.py` checks, the wiring in
   `tools/validate.py`, and their tests.
6. The fixture and the two cases.

No intermediate commit states something false.

## Data model

None. area54 stores no data (ADR-0001). The new structures are a module constant
`TEAM_PATH`, a heading constant in `tools/agents.py`, and the parsed section — a
list of `(start_line, items)` tuples held only during a check.

## Interfaces

| Surface | Contract |
| --- | --- |
| `tools.constitution.validate(path: Path = TEAM_PATH) -> list[str]` | Failures, one string each. Raises `ConstitutionError` if the file is missing or has no `## Escalation`. |
| `python tools/validate.py` | **Unchanged — no arguments.** Adds `validate_constitution()` to the sum at `tools/validate.py:44`, against this repo's `team/TEAM.md`. |
| `tools.agents.validate()` | Unchanged signature; two more per-agent checks. |
| `team/TEAM.md` `## Escalation` | Escalate-immediately list first, never-surface list second, both top-level Markdown lists, ≥5 items each. |
| `python -m tools.deploy <target> --check` | Unchanged. Reports `.claude/TEAM.md` changed, because `team/TEAM.md` changed. |

## Dependencies

**None added.** Section slicing and list counting are ~40 lines of `re` and
string handling, under the CLAUDE.md fifty-line threshold. Rejected: a Markdown
parser (`markdown-it-py`, `mistune`) — a real AST for a job needing two
line-shape predicates, and the first runtime dependency in a package that
deliberately has almost none.

## Migration and rollout

Backward compatible. No backfill, no flag, no runtime state. The change is text
plus one module; `git revert` of the PR restores the constitution whole.

- **Target repos go stale on merge, deliberately.** `team/TEAM.md` changes, so
  `deploy --check` diffs it against the target's `.claude/TEAM.md` and exits
  non-zero naming that destination (criterion 12). Nothing may exclude,
  normalise, or special-case `team/TEAM.md` in `tools/deploy.py` — that silences
  the signal the spec requires. Redeploying area52 needs its own roadmap line.
- **The contract takes effect on the next invocation, not mid-run.** area54
  builds itself with itself, so the agents running this PR operate under the old
  `## Escalation`. That is why step 1 precedes step 2.

`CLAUDE.md`'s Stack table needs no change. Its Commands row for
`python tools/validate.py` reads "Agent + command checks" and should read "Agent,
command and constitution checks" — the only `CLAUDE.md` edit.

## Risks

**The single-source rule decays back into duplication.** Likely, and the main
one. Nothing mechanically stops an agent definition from restating a list — the
check only asserts the section exists. Mitigated by the Lead's review and by the
two eval cases. Accepted.

**Ordinal identification misfires.** Low likelihood, contained: a third list
added above the two produces a wrong-but-loud failure with a line number, not a
silent pass. Accepted rather than mitigated.

**The checks pass on a contract that says nothing useful.** Certain, by design —
five bullets of nonsense pass criterion 1. That is what resolved question 4 buys:
a check that cannot decay into a wording lint.

**The eval cases assert regex proxies, not comprehension**, and no live trial can
complete today (`CLAUDE.md`). They are a statement of intent, not evidence.
Criterion 10 is written to that limit.

## Alternatives considered

**Extend `tools/settings.py`.** Rejected: every check there takes a parsed
`Settings` object and the module is about `.claude/settings.json`. A markdown
parser there makes the module about two unrelated files.

**Put the constitution check in `tools/agents.py`.** Rejected: `team/TEAM.md` is
not an agent definition. Criterion 8 *is* about agent definitions, and goes there.

**Restate the escalate-immediately list in each agent.** Rejected: nine copies
drift within weeks — the argument ADR-0001 used against the template repository.

**A canonical list file agents `Read` at runtime.** Rejected: an agent that must
open a second file to know whether to interrupt will sometimes not open it. The
constitution is already in every agent's context.

**Label-matched list identification** (`/immediately/`, `/never/`). Rejected by
resolved question 4 — it pins prose, and the section could not then be reworded
without touching the validator.

**A full Markdown AST.** Rejected: a dependency for two line predicates.

**A sixth eval primitive, or a semantic scorer.** Out of scope in the spec, and a
much larger change than this item.

## One finding against the spec, not fixed here

Criterion 2 says the escalate-immediately list covers those six entries **"at
minimum"**, while lines 32-40, criterion 5 and criterion 16 call the same list
**"the complete set"**. A floor and a closed set are different instructions, and
resolved question 6 compounds it by saying "all **five** categories are
confirmed" where criterion 2 names six and line 265 says six.

Resolved as an architecture call, since both readings produce different
constitutions: the list is **closed as categories** — nothing escalates that is
not an instance of one — and "at minimum" binds the *drafting*: the section must
name at least those six. A seventh category is a constitution change, never an
agent's call. This is what criterion 7 already assumes.

Reported rather than edited. The count discrepancy is the CPO's to correct.
