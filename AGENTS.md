# SlotScan Agent Guide

These instructions apply to the entire repository.

SlotScan is pre-launch development with no production users. Prefer hard cutovers:
do not add compatibility aliases, legacy routes, dual readers, or versioned cache
machinery.

## Validation policy

Use validation proportional to the change. Start with the smallest relevant
check and expand only when the affected surface or a failure warrants it.

- Documentation or comments only: review the diff; no project checks.
- Presentational frontend edits only (CSS/classes, spacing, typography, copy, or
  local markup with no behavior or accessibility change): do not add or run
  tests, install dependencies, or build. A visual check is optional when it is
  already convenient or the user requests it.
- Small isolated backend changes: run Ruff on the changed Python files and the
  smallest directly relevant existing unittest module or test case. Add a
  focused regression test for new behavior or a bug fix when existing coverage
  is insufficient; do not add tests for mechanical changes solely for process
  compliance.
- Frontend behavior changes: run the smallest directly relevant existing
  Playwright test when one exists. Shared hooks, API types, routing, providers,
  dependencies, or configuration require a frontend build.
- Broad or cross-cutting backend changes require the full backend checks.
  Database model, repository, or migration changes also require `alembic check`.

Do not validate an untouched subsystem. Do not repeat a successful check unless
relevant code changed afterward. Run `npm ci` only for dependency/lockfile work,
a requested clean install, or release validation. When uncertain between
validation levels, use the next higher level. Report checks run and checks
intentionally skipped in the final handoff.

Run the applicable full checks when the user requests them, the change is
cross-cutting or difficult to isolate, dependencies/build configuration/test
infrastructure change, an API contract changes across backend and frontend, or
before an authorized non-documentation commit, push, or deployment.

### Full backend checks

Run from `backend/` using the repository virtual environment:

```bash
ruff check app tests
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m compileall -q app alembic
venv/bin/alembic check
```

### Full frontend checks

Run from `frontend/`:

```bash
npm ci
npm run build
```

Do not deploy, restart production, change production configuration, or push
commits unless the user explicitly authorizes that action. Never print or copy
values from `.env`; it contains RPC and API credentials.

## Mobile display guidelines

- The page never scrolls horizontally; wide tables scroll only inside their
  `DataTable` container.
- On narrow screens hide secondary table columns with `hidden sm:table-cell`,
  and put column widths on header cells (not `<colgroup>`) so a hidden column's
  width collapses with it; freed width goes to the primary value column.
- A single value never soft-wraps on mobile: render a compact single-line form
  (middle-truncation) and keep the full value reachable via copy action or
  popover. Full-length values are a `sm:`-and-up affordance.
- Controls share one height and wrap as whole units into full-width rows.
- Small touch targets use `.touch-hitbox`.
- Reuse the shared primitives (`DataTable`, `HoverCell`, `DetailPopover`,
  `ViewSwitch`, `CopyButton`) instead of page-local variants.

## Private operations runbook

Production topology, hostnames, server paths, deployment and rollback
procedures, and other operational details belong in `AGENTS.private.md`. That
file is intentionally ignored and must never be committed.

Read the private runbook only when it is available locally and an operational
task is explicitly authorized. If it is unavailable, ask the user for the
required operational context instead of inferring hostnames or procedures.
