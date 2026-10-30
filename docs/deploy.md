# Deploying Mealwright (free tiers)

A public deploy for $0 a month:

| Part | Host | Free tier notes |
|---|---|---|
| Web (Next.js) | Vercel | Hobby plan. |
| API (FastAPI) | Render, `render.yaml` | Sleeps after 15 minutes idle; the first request after that takes ~30 s. No separate worker on the free plan, so `WORKER_IN_API=true`: pasted receipts are read in the API process, receipt **photos are off** (OCR lives in the worker image), and reminders only go out while the API is awake. |
| Postgres + pgvector | Neon | 0.5 GB: the full local database is ~0.3 GB. |
| Redis | Upstash | 10,000 commands a day; with the worker in the API nothing polls it. |
| Sign-in | Clerk | Use a **production** instance on a domain you own, or keep the development instance (fine for a demo, with a "Development mode" badge). |

You create the accounts and paste every secret into the providers' dashboards. Nothing
secret goes into the repository.

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
two-minute, one-use Clerk sign-in ticket (no public password). Its data resets every night at
03:00 UTC, it never calls a model (no spend) and it can't be deleted.

1. In Clerk, create a user (any email you control) and copy its **user id** (`user_...`).
2. Set `DEMO_CLERK_USER_ID` (Vercel) and `DEMO_AUTH_SUBJECT` (Render) to that id, and
   `NEXT_PUBLIC_DEMO=1` on Vercel; redeploy the web app.
3. Run the reset once to create its profile and pantry (after that it runs nightly; on the
   free plan only if the API is awake at 03:00 UTC, so run it by hand whenever you want a fresh
   start), on your machine with `DATABASE_URL` pointing at Neon:

```sh
uv run python -c "import asyncio; from larder_api.demo import reset_demo; from larder_db.engine import make_engine, make_sessionmaker; asyncio.run(reset_demo(make_sessionmaker(make_engine()), 'user_...'))"
```

## Paid upgrades, when wanted

- Always-on API and a separate worker (receipt photos, punctual reminders): a Render Starter
  instance (or Fly.io) for the API, plus a background worker from the same Dockerfile
  (`docker build --target worker`), with `WORKER_IN_API` unset.
