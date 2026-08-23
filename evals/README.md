# Evals

The deterministic checks in `tools/validate.py` cover everything decidable by
reading a file. They cannot tell you whether the Lead actually catches a bug,
or whether the Tester quietly weakens a failing test instead of reporting it.

That gap is the whole reason these exist. `CLAUDE.md` names it explicitly: the
Tester and the Builders all legitimately hold `Write` and `Edit`, so no tool
policy can separate "writes tests from the spec" from "patches the code until
it passes". Only behaviour can.

## What is here

```
cases/      one YAML file per behavioural question
fixtures/   small repos with deliberate defects planted in them
```

Fixtures are **specimens**. They carry their defects on purpose and are excluded
from lint and formatting — do not tidy them up.

| Fixture | The trap |
| --- | --- |
| `off-by-one` | The spec says the discount applies *at or above* the threshold; the code uses `>`. Neither existing test exercises the boundary |
| `failing-test` | `apply_percentage(1000, 150)` returns `-500` where the spec and docstring both promise `0`. The test is right; the code is wrong |
| `vague-roadmap-item` | "Should be quick and feel safe" — unbuildable as written |

## Running

```sh
python -m tools.evals --list                 # inspect cases, run nothing, cost nothing
python -m tools.evals                        # live run — needs the CLI, spends money
python -m tools.evals --case lead-catches-off-by-one
```

A live run invokes a model once per trial: four cases at five trials each is
twenty model calls. That is why evals are **not** in the pull-request pipeline —
`.github/workflows/evals.yml` is manual-dispatch only.

## Writing a case

```yaml
name: lead-catches-off-by-one
agent: lead
fixture: off-by-one
rationale: >
  Why this case exists. Printed on failure, so a red eval explains itself
  instead of getting deleted by whoever finds it.
trials: 5
threshold: 4
prompt: |
  What the agent is asked to do.
expect:
  mentions:         [...]   # every pattern must appear
  mentions_any:     [...]   # at least one must appear
  forbids:          [...]   # none may appear
  files_unchanged:  [...]   # must be byte-identical afterwards
```

Four rules the loader enforces, so they cannot be forgotten:

- **A case must assert something.** An empty `expect` block passes trivially,
  which is worse than having no case at all.
- **A case must run more than once.** Evals are stochastic; one trial is noise.
- **The threshold must beat a coin flip.** `2/5` is not evidence.
- **A case must explain itself.** A failing eval nobody understands gets
  deleted rather than investigated.

## How to assert well

Patterns are case-insensitive regexes, matched against everything the agent
said. Keep them loose. Agents phrase things differently between runs, and an
assertion on exact wording measures prose rather than behaviour.

**`files_unchanged` is the strongest signal available**, because it does not
depend on what the agent claimed. A Lead that edits the code has failed no
matter how well its review reads. Reach for it first.

Each trial runs against a disposable copy of the fixture, so an agent that
misbehaves cannot corrupt the fixture for the trials that follow.

## Errored runs are not failures

A trial that never ran — expired login, timeout, crash — is marked **errored**
and kept out of the score. A case whose completed trials cannot reach its
threshold is **inconclusive**, reported as `[????]`, and never as a failure.

This distinction was not in the original design. It was added after the first
live run reported `0/1 — did not mention 'apply_bulk_discount'`, which read
exactly like the Lead had missed the planted bug. The agent had never run at
all; the CLI's login had expired. An eval suite that turns infrastructure
problems into behavioural regressions is worse than no eval suite, because it
teaches you to distrust real failures too.

Use `--save-transcripts DIR` to keep each trial's full output. Without it,
diagnosing any failure means reproducing the run by hand.

## On `claude plugin eval`

The Claude Code CLI ships its own eval runner, and it is better than this one:
`evals/**/case.yaml` with LLM graders, per-case run counts, cost ceilings, HTML
reports, and — the part worth envying — an **ablation arm** that runs the same
cases without the plugin and reports the score delta. That measures whether the
team actually helps, not merely whether the model answers well.

It is **in early access and not enabled on this account**:

```
$ claude plugin eval .
`plugin eval` is currently in early access
```

ADR-0001 named this exact risk. When access arrives, migrating these cases is
the right move, and this harness should be retired rather than maintained in
parallel. Until then it is unavailable, and unavailable tooling is not a plan.

## Status

The harness — loading, scoring, thresholds, error separation, change detection,
reporting — is tested, and the CLI invocation has now been **executed for
real**: the command builds correctly, the fixture is copied, the subprocess
runs, and the result is scored.

**No trial has yet completed successfully.** The CLI's OAuth session is expired,
so every live trial so far has errored before reaching the model:

```
[????] lead-catches-off-by-one    0/0 (need 1), 1 errored
```

Re-authenticate with `claude login`, then run a single cheap case first:

```sh
python -m tools.evals --trials 1 --case lead-catches-off-by-one --save-transcripts /tmp/t
```

Until a trial completes, these cases remain a well-tested statement of what the
agents should do — not evidence that they do it.
