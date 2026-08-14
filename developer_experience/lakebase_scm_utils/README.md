# Lakebase SCM Utils — the portable branching + SCM engine

[`@databricks-solutions/lakebase-scm-utils`](https://github.com/databricks-solutions/lakebase-scm-utils)
is the Lakebase SCM and substrate engine: the portable core that owns database
branching, the paired-branch SCM workflow state machine, connection and
credential minting, schema migration, project scaffold and deploy primitives,
and the shared git / GitHub / util layer.

**Why it exists.** These SCM workflows and their supporting substrate were
originally embedded in [`consort`](../consort/) alongside the agentic
orchestration. They were extracted into this package so that both the
[VS Code / Cursor extension](../lakebase_scm_extension/) and the Consort kit can
depend on a single, versioned engine — easier to consume, and portable.

## Two consumption surfaces

**Library API** — for the extension and the Consort orchestration. Import the
substrate from the package barrel or a sub-path:

```ts
import { createBranch, getConnection } from "@databricks-solutions/lakebase-scm-utils";
import { resolveGitHubToken } from "@databricks-solutions/lakebase-scm-utils/github";
```

**CLIs** — for scaffolded projects and CI: the `lakebase-*` and `lakebase-scm-*`
bins, resolved on PATH by the `lk` shim.

## What it owns

| Capability | What it provides |
|------------|------------------|
| **Database branching** | Create, connect to, and tear down copy-on-write Lakebase branches |
| **Paired-branch SCM** | The workflow state machine that keeps a code branch and its database branch in step |
| **Credentials** | Short-lived connection + credential minting for a branch endpoint |
| **Migrations** | Schema-migration primitives run against a branch |
| **Scaffold + deploy** | Project scaffold and deploy primitives shared by the extension and Consort |

## Install

Consumed via a GitHub ref (npm publish is deferred):

```bash
npm install github:databricks-solutions/lakebase-scm-utils#v<version>
```

The package ships a pre-built `dist/` on every tagged release, so a consumer
install skips the build.

## How this fits with the other Developer Experience examples

This package is the shared foundation for the other two:

- [`lakebase_scm_extension`](../lakebase_scm_extension/) is the IDE surface over
  this engine.
- [`consort`](../consort/) layers its spec-first, test-driven agentic
  orchestration on top of it.

> **A pointer to an external package, not a `databricks bundle deploy`.** This
> engine ships no `databricks.yml` here — it is installed from
> [`databricks-solutions/lakebase-scm-utils`](https://github.com/databricks-solutions/lakebase-scm-utils)
> as a dependency of the extension and Consort. This folder is a guide to what it
> is and how to consume it; the source of truth is the package repository.
