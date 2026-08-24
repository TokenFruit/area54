# Token Fruit — area54

**A virtual software development team powered by agentic AI**, which Token Fruit
deploys to work on its products. Target repositories are named by the CPO.
area54 is independent of Gempli (`area53`) and is not deployed there.

The team is the product. area54 builds itself using itself: every change here
goes through the same seven roles and two approval gates it ships to everyone
else. Stack decision: [`docs/adr/0001-stack.md`](docs/adr/0001-stack.md).

## The team

Eight agents in `agents/`, each with a fresh context, its own tool allowlist,
and one job:

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

## How it reaches a product repo

area54 **is** a Claude Code plugin: `.claude-plugin/plugin.json` at the root,
components discovered by convention from `agents/`, `commands/`, `hooks/` and
`bin/`. The repo is also its own marketplace, so a product repo installs it by
name and a prompt fix arrives by version bump.

```
python -m tools.deploy /path/to/repo
```

That writes three files and two settings keys — the permission list, the
constitution, the PR template — and nothing else. The eighteen files that used
to be copied now live in the plugin. `.claude/TEAM_VERSION` records which
version a repo has; `claude plugin details area54` says what actually loaded.

area54 installs its own plugin the same way, from its own checkout: the team
that builds this repo is the artefact product repos get.

Start with [`CLAUDE.md`](CLAUDE.md) — the team constitution — and
[`docs/roadmap.md`](docs/roadmap.md), which is the only input to everything.
