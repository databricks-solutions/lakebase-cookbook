# Consort — spec-first, test-driven agentic development on Lakebase branches

[Consort](https://github.com/databricks-solutions/consort) keeps AI-written code
clean and correct: spec-first and test-driven, driven by a deterministic state
machine with human-approval gates and immutable tests. Every "green" is a real
test run on a live Lakebase database branch, enforced by hard rules rather than
soft prompts, so engineering discipline is not left to the whim of a model.

Consort takes its name from music: a *consort* is an ensemble that plays in
concert, each musician holding one part while a conductor keeps them in time.
Consort applies that to building software — a set of agents each take on one
familiar role from the software lifecycle while a deterministic conductor keeps
them in sequence and a human approves every gate.

## Why it uses Lakebase

The database is the hardest dependency to get right, because it is the one you
can't cheaply branch: it gets faked with mocks that drift from production, or
shared across a staging box the tests quietly diverge from. Lakebase removes
that constraint — a database branch is a real, governed, copy-on-write copy
created in about a second. Consort builds on that to make an agent's "done"
checkable:

| Property | What it means |
|----------|---------------|
| **Verified against real data** | "Green" means a real test runner passed against a live Lakebase database branch, not an agent's say-so |
| **Independently reviewed** | The agent that writes the code is never the one that judges it |
| **Spec-first and immutable** | Intent is frozen at a hashed gate; within a unit of work, tests can't be edited to force a pass |
| **Deterministically driven** | The control loop is codified, so it can't drift, skip a step, or get lost after a long session |
| **Human-gated** | Gates fail closed; nothing advances past one without your approval |

## The ensemble

Each agent owns one concern and communicates only through the artifacts it
produces and consumes, in the order a lifecycle would run them.

| Agent | Lifecycle role | Owns |
|-------|----------------|------|
| **Product Owner** | Product | the backlog and each story's acceptance criteria |
| **Spec Author** | Analysis | the structured, testable specification |
| **Architect Reviewer** | Architecture | the layering lens, NFRs, and persistence invariants |
| **DBA** | Data | the physical schema and the per-story migration plan |
| **Test Strategist** | Test design | the ordered master test list drawn from the ACs |
| **UX Designer** | Experience | the interface design, for user-facing work |
| **Navigator** | Test + review | the failing test (RED), and review of the code that answers it |
| **Driver** | Implementation | the code that makes the test pass (GREEN), then refactors |

A deterministic conductor sequences them; no agent plays another's part.

## How it runs

Consort drives a spec-first design lane and then a branched-database TDD build
lane, stopping at every gate:

- at the **design gate**, you review and approve the frozen spec — the stories
  and acceptance criteria, the ordered test list, and the DBA's schema plan;
- through the **build**, each cycle writes a failing test, makes it pass against
  a live Lakebase database branch, then refactors;
- at the **deploy** and **promote** gates, you approve the release and the
  migration to the parent tier.

## Getting started

Consort is distributed from its own repository. The short path:

```bash
# 0. Bootstrap and run the environment doctor (needs a Lakebase-enabled workspace)
bash <(curl -sL https://raw.githubusercontent.com/databricks-solutions/consort/main/bootstrap.sh)

# 1. Install the Claude Code plugin
claude plugin marketplace add databricks-solutions/consort
claude plugin install consort@databricks-solutions

# 2. Launch Claude Code and start
#    run /consort:start in the session
```

Then walk the [`examples/first-project/`](https://github.com/databricks-solutions/consort/tree/main/examples/first-project)
step-by-step first session (install to first shipped feature) using the
StockFlow sample warehouse app. Other coding agents (Cursor, Genie Code, MCP
clients) are supported via `install.sh`.

## How this fits with the other Developer Experience examples

Consort sits on top of the same Lakebase branching primitives the rest of this
category uses:

- [`lakebase_scm_utils`](../lakebase_scm_utils/) is the portable engine (branching,
  the paired-branch SCM state machine, credentials, migrations) that Consort
  builds its orchestration on.
- [`lakebase_scm_extension`](../lakebase_scm_extension/) is the VS Code / Cursor
  extension that pairs a Git branch with a Lakebase branch in the editor.

> **A pointer to an external project, not a `databricks bundle deploy`.** Unlike
> the deployable cookbook examples, Consort ships no `databricks.yml` here — it
> is installed from
> [`databricks-solutions/consort`](https://github.com/databricks-solutions/consort)
> and run against a Lakebase-enabled workspace you provision separately. This
> folder is a guide to what it is and how to start; the source of truth is the
> Consort repository.
