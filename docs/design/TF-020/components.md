# TF-020 — components

**Read `README.md` first.** There are no UI components in this feature and no
component library to draw from — area54 has no client and renders nothing. What
follows is the reduced form of this file that does apply: the **render and input
primitives** the Builder would otherwise reinvent at each call site, marked
`[existing convention]` where this repo already has one and `[new]` where it
does not. The bias is unchanged: an existing convention is always the better
answer, and each new one is justified.

## Render primitives

### `[existing convention]` — the phase result line

`tools/telemetry.py:105-110`. Two-space indent, a label padded to a fixed
column, then the value. Used for every counts line in S1 and S2.

    analysed             11 of 14

Reuse the padding width already in use (20) rather than picking a new one, so
`propose` output sits next to `telemetry` output without looking foreign.

### `[existing convention]` — the check line

`tools/merge_gate.py:213`. `  [PASS] name    detail` / `  [FAIL] …`. Used for
the three gates in S2 — ceiling, staging agreement, scope. Same reason the merge
gate uses it: the verdict is a word at a fixed column, so it survives grep,
`NO_COLOR`, and being read aloud.

### `[existing convention]` — the failure prefix

`::error::`, as `tools/telemetry.py:132` and `tools/merge_gate.py:208`. Every
non-zero exit path in S1, S2, S5 and S7 leads with it. It is the GitHub Actions
annotation form and this repo already treats it as the failure marker.

### `[existing convention]` — the section rule

`── name ──`, `tools/telemetry.py:129`. Decoration only; every section is also
identifiable by its leading label, so nothing is lost when box characters do not
render.

### `[new]` — the evidence block

    [n] YYYY-MM-DD  session <short-id>
        > <verbatim line>
        <path to raw transcript>

**Justified:** nothing in this repo renders a quotation, and the shape carries
three of the spec's requirements at once — verbatim text marked as quoted (`>`),
attribution to a session (criterion 11), and the retained raw path (criterion 4)
so a claim can be checked against the original without leaving the terminal.

Rules: the `>` marker is mandatory on every quoted line, including continuation
lines. Truncation always states the omitted line count. The tool never re-wraps
a quoted line — a wrapped quote is no longer visibly verbatim.

### `[new]` — the review card

The full S6 layout. **Justified:** it is the human decision surface the whole
feature exists for, and its field order is a design decision (evidence before
diff) rather than a formatting one. Composed from the primitives above plus the
diff renderer.

Field order is fixed and not the Builder's to vary: target · instruction · gap ·
re-proposal marker · evidence · diff · eval coverage · prompt.

### `[existing, from outside]` — the unified diff

Standard `@@` unified hunks, as `difflib.unified_diff` produces and as `git
diff` prints. **Do not invent a friendlier diff format.** The CPO reads `git
diff` daily; an unfamiliar rendering of a familiar thing costs more than it
gives, and criterion 9 requires the proposal's hunks to be comparable against an
independently taken diff — same format, trivially comparable.

## Input primitives

### `[new]` — the single-keypress decision prompt

The only interactive element in area54. **Justified:** criterion 11 requires a
separate accept-or-reject per edit and there is nothing here to reuse.

Contract, and it holds everywhere the prompt is used:

- Keys `a` `r` `s` `v` `?` `q`, each with a spelled-out long form accepted too.
- **No default.** Enter alone re-prompts. An unrecognised key re-prompts with a
  one-line legend. Nothing an impatient CPO can lean on writes a file.
- Case-insensitive.
- `v` and `?` are non-consuming: they print and re-prompt the same edit.
- Ctrl-C and EOF are `q`: abandon, write nothing, remember nothing.
- The legend prints before the first prompt, not only under `?`.

### `[new]` — the aggregate confirmation

A single `y/N` before any write, defaulting to **No**, naming the files. The
destructive-action rule; see `states.md` S7.

### `[existing convention]` — the TTY gate

`sys.stdin.isatty() and sys.stdout.isatty()`, checked before anything else in
`apply`. Not a component so much as a precondition, listed here because it is
the one place a Builder might reasonably add a `--yes` escape hatch for
testability. **It must not exist.** Test the review loop by calling its
functions, never by adding a flag that lets something other than a person say
yes.
