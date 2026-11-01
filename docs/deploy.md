# Deploying Mealwright (free tiers)

A public deploy for $0 a month:

| Part | Host | Free tier notes |
|---|---|---|
| Web (Next.js) | Vercel | Hobby plan. |
| API (FastAPI) | Render, `render.yaml` | 0.1 CPU and 512 MB. Sleeps after 15 minutes idle, and takes about a minute to wake (see "Which Render plan" below). No separate worker on the free plan, so `WORKER_IN_API=true`: pasted receipts are read in the API process, receipt **photos are off** (OCR lives in the worker image), and reminders only go out while the API is awake. |
| Postgres + pgvector | Neon | 0.5 GB and 100 compute-hours a month: the full local database is ~0.3 GB, and it sleeps when idle. |
| Redis | Upstash | 500,000 commands a month; with the worker in the API nothing polls it, and public routes don't count in it. |
| Sign-in | Clerk | Use a **production** instance on a domain you own, or keep the development instance (fine for a demo, with a "Development mode" badge). |

You create the accounts and paste every secret into the providers' dashboards. Nothing
secret goes into the repository.

Before a deploy, run the dependency audit from the Actions tab (`audit.yml`).
`docs/security-review.md` lists what was reviewed and what was accepted.

## Which Render plan

**The free plan, as `render.yaml` sets it up, plans as well as a paid one. It just takes longer.**
Measured in the real API image, capped with Docker at each plan's CPU and memory, on 10 bench
profiles with one worker:

| Limits | Monthly | Planner time limit | Plan, one snack (p50) | Plan, three snacks (p50) | Found by CP-SAT | Hard misses | Objective cost (one snack) | First catalogue load |
|---|---|---|---|---|---|---|---|---|
| 0.1 CPU, 512 MB (Free) | $0 | **15 s, as set here** | 15.2 s | 15.2 s | 20 of 20 | 0 | £21.98 | 25 s |
| 0.1 CPU, 512 MB (Free) | $0 | 8 s | 8.2 s | 8.2 s | 16 of 20 | 2 | £35.64 | 23 s |
| 0.1 CPU, 512 MB (Free) | $0 | 3.5 s, the default | 3.8 s | 11.5 s | 8 of 20 | 2 | £42.59 | 26 s |
| 0.5 CPU, 512 MB (Starter) | $7 | 3.5 s | 3.5 s | 3.5 s | 20 of 20 | 0 | £21.85 | 3.6 s |
| 1 CPU, 2 GB (Standard) | $25 | 3.5 s | 3.5 s | 3.5 s | 20 of 20 | 0 | £21.34 | 1.8 s |

What the free plan costs is time: about a minute to wake, about 25 s to load the catalogue for the
first plan or recipe search after that, and 15 s for each new plan. Only one plan runs at a time,
so a second visitor waits for the first. Swapping a meal takes about 3 s: with `REPLAN_TIME_LIMIT_MS`
at 3 s, CP-SAT made 5 of 6 swaps, with no hard misses and only the swapped meal changed (all 6 fell
back to greedy at the default 1 s, also with no misses). The server stays responsive during a solve,
with at most 0.05 s of delay to other requests, so Render's 5-second health check isn't at risk.

If you send the link to someone who won't wait, open the site yourself first, or move to Starter
(`plan: starter` in `render.yaml`, and drop the three limits below it), which doesn't sleep. Peak memory in this test stayed under 256 MB at every size,
and the API server idles at about 260 MB, so 512 MB should hold one plan at a time. Watch it after
the first deploy, since the test didn't run the server itself.

These ran on a development machine with a local database, so hosted plans will be somewhat slower.
If plans come back worse there, or take longer than you'd like, `PLAN_TIME_LIMIT_MS` is the setting
to change. Swaps were measured with the planner directly, not through the whole API.

## 1. Database (Neon)

1. Create a project (region: Frankfurt, close to Ireland) and copy the connection string.
2. Turn it into the asyncpg form the API uses:
   `postgresql+asyncpg://USER:PASSWORD@HOST/DB?ssl=require` (drop `sslmode=...` and
   `channel_binding=...`; asyncpg takes `ssl=require`).
3. Enable pgvector: `CREATE EXTENSION IF NOT EXISTS vector;` in Neon's SQL editor.
4. Copy your local data across (foods, recipes, ingredient matches; about 5 minutes):

```sh
docker compose exec -T db pg_dump -U larder -d larder --no-owner --no-privileges -Fc > larder.dump
pg_restore --no-owner --no-privileges -d "postgresql://USER:PASSWORD@HOST/DB?sslmode=require" larder.dump
```

   Optional, to leave more room: the API never reads embeddings (they're only for the data
   pipeline), so `TRUNCATE food_embeddings, recipe_embeddings;` on Neon frees ~30 MB.
   Your own local test users come along with the dump; delete them on Neon if you like.

## 2. Redis (Upstash)

Create a Redis database (region: eu-west-1) and copy the `rediss://` URL (TLS).

## 3. API (Render)

1. New → Blueprint → this repository. Render reads `render.yaml`.
2. Fill in the secrets it asks for:
   - `DATABASE_URL`: from step 1 (asyncpg form).
   - `REDIS_URL`: from step 2.
   - `CORS_ORIGINS`: `["https://YOUR-APP.vercel.app"]` (the web app's address; JSON list).
   - `CLERK_PUBLISHABLE_KEY`: from Clerk.
   - Optional: `ANTHROPIC_API_KEY` (food matching; per-user monthly cap $1 by default),
     `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` (reminders; `uv run larder-vapid`),
     `OFF_USER_AGENT` (barcode lookups), `DEMO_AUTH_SUBJECT` (step 5).
3. Deploy. Migrations run when the container starts. Check `https://YOUR-API.onrender.com/readyz`.

Rate limits (`larder_api/ratelimit.py`) count per user, per link or per client address in the
same Redis. `render.yaml` sets `TRUSTED_PROXY_HOPS=1` so the client's address comes from the
`X-Forwarded-For` entry Render's proxy adds. On a host with no proxy in front, leave it at 0:
the header is then ignored, since anyone can send it. A limit can be raised by name with
`RATE_LIMIT_OVERRIDES='{"import_read": 100}'`.

## 4. Web (Vercel)

1. New Project → this repository. Root directory: `apps/web`. Framework: Next.js. Install
   command: `pnpm install` (Vercel reads the workspace's `pnpm-lock.yaml`).
2. Environment variables:
   - `NEXT_PUBLIC_API_URL`: `https://YOUR-API.onrender.com`
   - `API_URL`: the same (server-side calls).
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`: from Clerk.
   - Optional demo (step 5): `DEMO_CLERK_USER_ID` and `NEXT_PUBLIC_DEMO=1`.
3. Deploy, then add the Vercel address to Clerk's allowed origins (production instances) and
   to `CORS_ORIGINS` on Render.

## 5. The demo account (optional)

"Try the demo, no sign-up" on the landing page signs visitors into one shared account with a
two-minute, one-use Clerk sign-in ticket (no public password). Its data resets every day at
03:00 UTC, or when the API next wakes after that. It never calls a model (no spend), can't be
deleted, and makes no share links, calendar feeds or reminders, because anyone can sign in as it.

1. In Clerk, create a user (any email you control) and copy its **user id** (`user_...`). Leave
   multi-factor authentication off on this instance: a visitor could otherwise enrol a second
   factor on the shared user and lock everyone out.
2. Set `DEMO_CLERK_USER_ID` (Vercel) and `DEMO_AUTH_SUBJECT` (Render) to that id, and
   `NEXT_PUBLIC_DEMO=1` on Vercel; redeploy the web app.
3. Nothing else is needed with `WORKER_IN_API=true`: the API creates the demo's profile and pantry
   when it starts. With a separate worker that waits for 03:00 UTC. To start afresh by hand, run
   this on your machine with `DATABASE_URL` pointing at Neon:

```sh
uv run python -c "import asyncio; from larder_api.demo import reset_demo; from larder_db.engine import make_engine, make_sessionmaker; asyncio.run(reset_demo(make_sessionmaker(make_engine()), 'user_...'))"
```

## Updating the recipes

Migrations run when the container starts, but recipes don't: a free-tier API sleeps and wakes all
day, and it shouldn't re-import each time. The first deploy gets them from the dump in step 1. After
a change to `curated.toml`, `aliases.csv` or `food_tags.csv`, run these on your machine with
`DATABASE_URL` pointing at Neon:

```sh
uv run larder-data import-curated
uv run larder-data resolve --aliases-only
```

Both are safe to run again, take seconds and need no model or API key. The API keeps its catalogue
for a day on the free plan (`CATALOG_TTL_S`), so restart it in Render's dashboard to pick up the
change at once. Plans already made stay as they are.

The import adds and updates but never deletes, because saved plans may point at a recipe. A recipe
renamed in `curated.toml` under a new `slug` stays in the database under its old one and can still
be planned, so keep slugs stable once deployed.

## Paid upgrades, when wanted

- Always-on API and a separate worker (receipt photos, punctual reminders): a Render Starter
  instance (or Fly.io) for the API, plus a background worker from the same Dockerfile
  (`docker build --target worker`), with `WORKER_IN_API` unset.
