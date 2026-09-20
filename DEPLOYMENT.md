# Deploying Vaulto

## Read this first: you need three services, not two

Vercel and Supabase are two of them. The FastAPI backend needs a third.

| Piece | Where | Why |
|---|---|---|
| **Frontend** (Next.js) | **Vercel** | What it is built for |
| **Database + Auth** | **Supabase** | Managed; nothing to deploy |
| **Backend** (FastAPI) | **Render / Railway / Fly.io** | Needs a long-running process |

**Why the backend cannot go on Vercel.** Vercel runs Python as serverless
functions, frozen between requests. This backend:

- runs the **rate-alert checker in-process every 15 minutes** — a frozen
  function never ticks, so alerts would silently never fire;
- **migrates the database on startup** — a serverless app "starts" on every cold
  start, so that would run constantly;
- **fans out to 28 provider APIs** with a 15 s timeout each, which does not fit
  comfortably in a function's execution limit.

Render's free tier is the quickest third service (one caveat below). Railway and
Fly.io work identically from the same `backend/Dockerfile`.

> If you truly must have only two services, the honest option is to drop the
> in-process scheduler and drive `check_alerts` from an external cron. That is a
> code change, not a config one — ask and I will do it as its own piece of work.

---

## Step 1 — Supabase

1. [database.new](https://database.new) → create a project. Pick the region
   closest to your users; **save the database password**, it is shown once.
2. Wait for provisioning (~2 min).
3. **Authentication → Providers → Email** — on by default. Decide about
   **Confirm email**:
   - **On** (default, recommended): new users get a code/link to verify. The app
     handles both — there is a code box on `/auth` and `/reset-password` catches
     the link.
   - **Off**: sign-up signs the user straight in. Fine for a demo.
4. **Google sign-in** *(optional)* — **Authentication → Providers → Google**.
   You need an OAuth client from the
   [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
   *Create Credentials → OAuth client ID → Web application*, with the
   **Authorised redirect URI** set to the callback URL Supabase shows you on
   that provider page (`https://YOURREF.supabase.co/auth/v1/callback`). Paste the
   client ID and secret back into Supabase.
5. **Authentication → URL Configuration** — the step everyone forgets. Until it
   is right, every confirmation and password-reset email links to `localhost`.
   - **Site URL**: `https://your-app.vercel.app`
   - **Redirect URLs** — add each of these:
     ```
     https://your-app.vercel.app/**
     http://localhost:3000/**
     ```
     The wildcard covers `/sso-callback`, `/reset-password` and `/post-auth`.
     Keep the localhost entry so local development still works.
6. Collect your keys now — **ENVIRONMENT.md** says exactly where each lives:
   project URL, anon/publishable key, service_role/secret key, and both
   connection strings (ports 6543 and 5432).

You do **not** need to run any SQL. The backend migrates itself on first boot,
and that includes enabling Row Level Security on every app table.

## Step 2 — Optional extras (2 minutes, skip if you like)

- **Redis cache** — [Upstash](https://console.upstash.com): create a database in
  the region nearest your *backend*, then copy the `rediss://…` string (Connect →
  redis-cli). Not the REST URL. See ENVIRONMENT.md.
- **Rate-alert email** — [Resend](https://resend.com/api-keys): create a key,
  and verify a domain if you want alerts to reach anyone other than yourself.

## Step 3 — Backend on Render

**Option A — Blueprint (uses the committed `render.yaml`)**

1. Push this branch to GitHub.
2. Render → **New → Blueprint** → select the repo → Apply.
3. Fill in every environment variable it prompts for (all blank by design, so
   nothing secret is in the repo). Use the checklist in ENVIRONMENT.md §5.

**Option B — by hand**

1. Render → **New → Web Service** → connect the repo.
2. **Runtime** Docker · **Dockerfile path** `backend/Dockerfile` ·
   **Docker context** `backend` · **Health check path** `/health`.
3. Add the environment variables from ENVIRONMENT.md §5.

Either way:

- **Set `ALLOWED_ORIGINS` to your Vercel URL.** You will not have it until step
  4, so put a placeholder in now and correct it at step 5.
- **A note on the free tier:** it sleeps after ~15 minutes idle. A sleeping
  backend means the first request takes ~30 s *and the alert checker does not
  run*, so rate alerts stop being delivered. Use a paid instance if alerts
  matter; for a demo the free tier is fine.
- Watch the deploy log for `Database schema is at head` and
  `Application startup complete`. Then check `https://your-api/health` →
  `{"status":"ok","service":"flint-api"}`.

## Step 4 — Frontend on Vercel

1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory: `frontend`.** This repo holds the backend and frontend
   together, so the default (the repo root) will not build. Vercel then detects
   Next.js and needs no other build settings.
3. Add the four frontend variables (ENVIRONMENT.md §5), ticking **Production,
   Preview and Development**. `NEXT_PUBLIC_API_URL` is the Render URL from step 3.
4. Deploy.

If a variable is missing the build **fails on purpose**, with a message naming
it. That is better than the alternative it replaced — a build that succeeded and
then pointed every visitor's browser at `localhost:8000`.

## Step 5 — Join the two up

1. Put the real Vercel URL into the backend's `ALLOWED_ORIGINS`
   (`https://your-app.vercel.app`, no trailing slash) and redeploy the backend.
2. Put it into Supabase → **Authentication → URL Configuration → Site URL** and
   the Redirect URLs, if you used a placeholder earlier.
3. If you want preview deployments to work too, set `ALLOWED_ORIGIN_REGEX` on the
   backend — see ENVIRONMENT.md §3.

## Step 6 — Verify, in this order

1. `GET https://your-api/health` → `{"status":"ok"}`
2. `GET https://your-api/api/providers` → a list of 28
3. Open the site, run a comparison **while signed out** — this exercises the
   frontend → backend path and CORS.
4. **Sign up** with a real address. With Confirm email on, you get a code:
   typing it on the page and clicking the link in the email should both work.
5. You should land on **/onboarding**, not /dashboard. Complete it.
6. Reload `/dashboard` — your profile persists, so the database write worked.
7. **Sign out, sign in again**, and visit `/settings` directly while signed out:
   it should bounce you to `/auth` and then return you to `/settings`.
8. Create a **rate alert** with a target the market has already passed, then
   watch the backend log at the next 15-minute tick. (Needs a non-sleeping
   instance and `RESEND_API_KEY`.)
9. Make yourself an admin: put your Supabase user UUID in `ADMIN_USER_IDS`
   (backend) and `NEXT_PUBLIC_ADMIN_USER_IDS` (Vercel), redeploy both, then open
   `/admin/analytics`.

## Step 7 — Custom domain (optional)

1. Vercel → Project → Settings → **Domains** → add it, follow the DNS records.
2. Then update, or auth will break in confusing ways:
   - backend `ALLOWED_ORIGINS` → add the new origin
   - Supabase **Site URL** and **Redirect URLs** → the new domain
   - Resend → verify the domain if you send alerts from it

---

## Troubleshooting

See the table at the end of **ENVIRONMENT.md** — it covers CORS, the localhost
bundle, `401`s, connection-string encoding and the localhost-in-email problem.

Two more that are specific to deploying:

**Backend won't start, log ends at the migration.** Read the traceback: it is
almost always `DATABASE_URL`. Check the password is percent-encoded and that you
used port 6543. To migrate by hand instead:
`cd backend && DATABASE_URL=… alembic upgrade head`.

**Vercel build fails with "No Next.js version detected".** Root Directory is not
set to `frontend`.

---

## What is actually running

```
Browser
  │
  ├── Vercel ─────────── Next.js pages + middleware.js
  │                      (middleware validates the Supabase session cookie
  │                       on /dashboard, /onboarding, /settings, /alerts,
  │                       /history, /admin before any HTML is sent)
  │
  ├── Supabase Auth ──── sign-in, sign-up, OAuth, password reset
  │                      (issues the JWT the browser sends onward)
  │
  └── Render ─────────── FastAPI
                           ├── verifies that JWT against Supabase's JWKS
                           ├── Supabase Postgres (transaction pooler)
                           ├── Upstash Redis (optional cache)
                           ├── 28 provider APIs
                           └── APScheduler → rate alerts → Resend
```

Only the frontend is on Vercel. Everything with a secret in it runs on the
backend, which is why the `service_role` key never reaches a browser.
