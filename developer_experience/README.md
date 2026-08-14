# Developer Experience

Examples that make building and shipping on Lakebase safer and faster —
branching, CI/CD, and change-management workflows.

| Example | Description |
|---------|-------------|
| [`branching_cicd/`](branching_cicd/) | A GitHub CI/CD workflow that forks a Lakebase branch per PR, runs the changed SQL there, posts an AI impact review, and applies migrations to production exactly once on merge. |
| [`consort/`](consort/) | An agentic development framework: a Scrum team rendered as role agents runs spec-first, test-driven development where every "green" is a real test on a live Lakebase branch, driven by a deterministic state machine with human-approval gates. |
| [`lakebase_scm_extension/`](lakebase_scm_extension/) | A VS Code / Cursor extension that replaces built-in Git source control with a unified Git + Lakebase provider, pairing each code branch with a Lakebase database branch. |
| [`lakebase_scm_utils/`](lakebase_scm_utils/) | The portable engine behind the extension and Consort: database branching, the paired-branch SCM state machine, credentials, and schema migration, as a library and CLIs. |
