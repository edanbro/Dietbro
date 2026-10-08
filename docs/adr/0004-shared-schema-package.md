# ADR-0004: Schema in a shared `larder-db` package; async SQLAlchemy everywhere

- Status: Accepted
- Date: 2026-10-08

## Context

The schema is needed by the API (M2+), the background worker (M6), the data importers (M1) and
the evals (M7). Choices:

1. **Models inside `apps/api`.** Simple now, but importers and the worker would then depend on
   the web app package, or duplicate models.
2. **Models in `packages/core`.** Core is meant to be pure domain logic with no I/O; pulling
   SQLAlchemy and pgvector into it couples the solver and evals to the database.
3. **A dedicated `packages/db` workspace member** with the SQLAlchemy models, engine helpers and
   the Alembic migrations, depended on by whoever needs persistence.

Separately: the API is async (FastAPI + asyncpg). Importers could use a sync driver
(psycopg) for simplicity, at the cost of two drivers and two session styles.

## Decision

Option 3, and async SQLAlchemy 2.0 + asyncpg for every consumer, importers included.

- `larder_db.models`: typed `Mapped[...]` models with a constraint naming convention.
- Alembic lives in the package (`script_location = larder_db:migrations`), async env.
- A test (`test_models_match_migrations`) runs autogenerate against the migrated database and
  fails on any difference, so models and migrations can't drift.
- `larder_db.testing` is a pytest plugin with Postgres fixtures shared by every package's tests.

## Consequences

- One mental model for DB access across API, worker and pipeline.
- Batch importers pay a little async ceremony; bulk writes use `INSERT ... ON CONFLICT` and
  executemany, which asyncpg handles well (8k foods + 15k portions import in ~10 s).
- Packages that need no database (`core`, future `solver`) stay free of SQLAlchemy.
