# Token Fruit — area54

**A virtual software development team powered by agentic AI**, which Token Fruit
deploys onto its product repositories — Gempli (`area53`), alloqo, flozeno,
izenesis, and whatever follows.

The team is the product. area54 builds itself using itself: every change here
goes through the same seven roles and two approval gates it ships to everyone
else. Stack decision: [`docs/adr/0001-stack.md`](docs/adr/0001-stack.md).

## The team

Seven agents in `.claude/agents/`, each with a fresh context, its own tool
allowlist, and one job:

| Agent | Job | Output |
| --- | --- | --- |
| `product-owner` | Roadmap item → buildable spec | `docs/specs/` |
| `architect` | Spec → technical decision | `docs/adr/` |
| `designer` | Spec → interaction design | `docs/design/` |
| `builder-backend` | Server implementation + unit tests | branch → draft PR |
| `builder-frontend` | Client implementation + unit tests | branch → draft PR |
| `lead` | Reviews the diff. Cannot write code. | PR comments |
| `tester` | Tests from the spec, not the code | `tests/` |
| `devops` | Pipeline, merge, release, rollback | Actions, releases |

## How to drive it

You are the CPO. You run six commands and make two decisions per feature.

```
/groom  <roadmap item>   → spec          → you approve
/design TF-NNN           → ADR + design
/build  TF-NNN           → code + draft PR
/review <PR>             → Lead + Tester verdicts
                         → you approve
/ship   <PR>             → merged, tagged, deployed to staging
/status                  → what is in flight, what needs you
```

## The three rules that make it work

1. **GitHub is the memory.** Agents are stateless; every handoff leaves a
   durable artifact — an issue, a committed file, a PR, a review comment.
   Nothing important lives in a chat.
2. **The reviewer cannot write code.** The `lead` agent has no edit tools. A
   reviewer that silently patches what it finds destroys the signal.
3. **CI decides whether tests pass.** An agent saying "tests pass" means it ran
   something. `.github/workflows/ci.yml` is the only trustworthy gate.

Start with [`CLAUDE.md`](CLAUDE.md) — the team constitution — and
[`docs/roadmap.md`](docs/roadmap.md), which is the only input to everything.
