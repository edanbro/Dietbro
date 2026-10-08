# ADR-0003: Monorepo with uv + pnpm workspaces, no task-runner framework

- Status: Accepted
- Date: 2026-10-08

## Context

The project has a Python side (API, worker, solver, LLM, data packages) and a TypeScript side
(Next.js web app). They share one contract (the API's OpenAPI schema) and should change together
in one PR. Options considered:

1. **Separate repos** for web and backend. Clean boundaries, but contract changes need two PRs
   and versioning; overkill for one developer.
2. **Monorepo with Nx / Turborepo / Bazel** for orchestration and caching. Strong at scale, but
   adds a framework to learn and configure for two languages and a handful of packages.
3. **Monorepo with native workspaces**: a uv workspace for Python (one lockfile, local packages as
   workspace deps) and a pnpm workspace for Node; a small Makefile for common commands; CI jobs
   per language.

## Decision

Option 3.

- `uv` workspace at the repo root: members `apps/api`, `packages/core` (more added at their
  milestone). One `uv.lock`; shared ruff / pyright (strict) / pytest config in the root
  `pyproject.toml`.
- `pnpm` workspace at the root with `apps/web`. One `pnpm-lock.yaml`.
- `compose.yaml` at the repo root so `docker compose up` works with no flags; `infra/` holds
  deploy and ops files (Fly, Grafana, k6) when they arrive.
- Web client types are generated from the committed `apps/api/openapi.json`
  (`make gen-api`); CI fails on drift.

## Consequences

- Fast, reproducible installs; one place to bump dependencies per language.
- No cross-language build cache; CI runs each language job in full. Fine at this size — revisit
  (new ADR) if CI time becomes a problem.
- Docker builds use the repo root as context so each image can see the workspace lockfile.
