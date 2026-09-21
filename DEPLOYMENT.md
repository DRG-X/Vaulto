# Deploying Vaulto

| Piece | Where |
|---|---|
| **Frontend** (Next.js) | **Vercel** |
| **Database + Auth** | **Supabase** |
| **Backend** (FastAPI) | **Google Cloud Run** |
| **The 15-minute alert tick** | **Supabase Cron** → an endpoint on Cloud Run |

Every environment variable named here, and the exact dashboard path to get it, is
in **[ENVIRONMENT.md](ENVIRONMENT.md)**.

## How rate alerts survive scale-to-zero

Cloud Run runs no container when no request is in flight, and you are not billed
for idle. That is the point of it — and it is fatal to a background scheduler.
This backend used to tick an in-process APScheduler job every 15 minutes; with no
process between requests, those ticks never happened and alerts silently stopped
being delivered.

So the schedule moved out of the app and into the database:

```
Supabase Postgres                          Cloud Run
┌──────────────────────────┐               ┌───────────────────────────┐
│ pg_cron: */15 * * * *    │   HTTPS       │ POST /internal/check-alerts│
│   └─ pg_net.http_post ───┼──────────────►│   ├─ CRON_SECRET checked  │
│        Authorization:    │  wakes an     │   ├─ single-flight lock   │
│        Bearer <secret>   │  instance     │   └─ check_alerts()       │
│           ▲              │  from zero    │        └─ Resend email    │
│  vault.decrypted_secrets │               └───────────────────────────┘
└──────────────────────────┘
```

Postgres is always running, so the schedule is always kept. Each tick is an
ordinary HTTPS request, which is exactly what starts a scaled-to-zero instance.
The alert logic itself is unchanged — only its trigger moved.

The endpoint runs the check **synchronously** and answers when the pass is done.
That is deliberate: Cloud Run throttles an instance's CPU once it has responded,
so answering early and finishing in the background is how you get a run that is
cut off partway through.

---

## Step 1 — Supabase

1. [database.new](https://database.new) → create a project. Pick the region
   closest to your users; **save the database password**, it is shown once.
2. **Authentication → Providers → Email** — on by default. Decide about
   **Confirm email**:
   - **On** (default, recommended): new users get a code/link to verify. The app
     handles both — there is a code box on `/auth` and `/reset-password` catches
     the link.
   - **Off**: sign-up signs the user straight in. Fine for a demo.
3. **Google sign-in** *(optional)* — **Authentication → Providers → Google**.
   You need an OAuth client from the
   [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
   *Create Credentials → OAuth client ID → Web application*, with the
   **Authorised redirect URI** set to the callback URL Supabase shows on that
   provider page (`https://YOURREF.supabase.co/auth/v1/callback`). Paste the
   client ID and secret back into Supabase.
4. **Authentication → URL Configuration** — the step everyone forgets. Until it
   is right, every confirmation and password-reset email links to `localhost`.
   - **Site URL**: `https://your-app.vercel.app`
   - **Redirect URLs**: add `https://your-app.vercel.app/**` and
     `http://localhost:3000/**`. The wildcard covers `/sso-callback`,
     `/reset-password` and `/post-auth`; keep localhost so local dev still works.
5. Collect your keys — ENVIRONMENT.md says where each lives: project URL,
   anon/publishable key, service_role/secret key, and both connection strings
   (ports 6543 and 5432).

You do **not** need to run any schema SQL. The backend migrates itself on first
boot, Row Level Security included. (The one piece of SQL you will run is the cron
job, in step 5.)

## Step 2 — Optional extras

- **Redis** — [Upstash](https://console.upstash.com): create a database in the
  region nearest your **Cloud Run region**, copy the `rediss://…` string
  (Connect → redis-cli). Not the REST URL. Beyond caching, this is also what
  makes the alert endpoint's single-flight lock work *across* Cloud Run
  instances rather than just within one.
- **Rate-alert email** — [Resend](https://resend.com/api-keys): create a key, and
  verify a domain if alerts should reach anyone other than yourself. Without
  this, alerts are evaluated and left armed but nothing is sent.

## Step 3 — Backend on Cloud Run

Generate the cron secret first — you need it in two places:

```bash
openssl rand -hex 32          # keep this, call it CRON_SECRET
```

**One-time project setup**

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

**Put the two real secrets in Secret Manager**, so they are not sitting in the
service's deploy config:

```bash
printf '%s' 'YOUR_CRON_SECRET'        | gcloud secrets create vaulto-cron-secret   --data-file=-
printf '%s' 'YOUR_SERVICE_ROLE_KEY'   | gcloud secrets create vaulto-supabase-srk  --data-file=-

# Let the service's runtime identity read them (default compute SA shown; use a
# dedicated service account if you have one).
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
for S in vaulto-cron-secret vaulto-supabase-srk; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

**Deploy** — straight from source, no local Docker needed. Cloud Build reads
`backend/Dockerfile`:

```bash
gcloud run deploy vaulto-api \
  --source backend \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 --memory 512Mi \
  --min-instances 0 \
  --max-instances 4 \
  --concurrency 40 \
  --timeout 600 \
  --set-env-vars "DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres" \
  --set-env-vars "DIRECT_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres" \
  --set-env-vars "SUPABASE_URL=https://YOURREF.supabase.co" \
  --set-env-vars "ADMIN_USER_IDS=YOUR_USER_UUID" \
  --set-env-vars "ALLOWED_ORIGINS=https://your-app.vercel.app" \
  --set-secrets  "CRON_SECRET=vaulto-cron-secret:latest" \
  --set-secrets  "SUPABASE_SERVICE_ROLE_KEY=vaulto-supabase-srk:latest"
```

Notes on those flags, because several are load-bearing:

- **`--allow-unauthenticated` is required, and is not as alarming as it looks.**
  The cron caller is a `pg_net` request from inside Postgres; it has no Google
  service account and cannot mint the OIDC token that IAM authentication needs,
  so an IAM-protected service is unreachable from Supabase Cron. The alert
  endpoint therefore carries its own door — `CRON_SECRET`, compared in constant
  time, failing closed. Every other route is either public by design or already
  behind a Supabase user token.
- **`--timeout 600`** must exceed a full alert pass, including a cold start. The
  default is 300s; raise it if you accumulate many distinct alert corridors.
- **`--min-instances 0`** is what makes this nearly free, and is safe precisely
  because the schedule no longer lives in the process. Set it to 1 if you would
  rather pay a little to avoid cold starts.
- **`--concurrency 40`** — the app is async and I/O-bound, so one instance
  handles plenty of comparison requests at once.
- If you percent-encoded characters in the database password, mind that `gcloud`
  also treats `,` specially in `--set-env-vars`; a repeated `--set-env-vars` flag
  per variable (as above) avoids that entirely.

**Grab the URL** — you need it for steps 4 and 5:

```bash
gcloud run services describe vaulto-api --region asia-south1 --format='value(status.url)'
```

Then confirm the service is alive and the alert endpoint is armed:

```bash
curl -s https://YOUR-SERVICE.a.run.app/health
#   {"status":"ok","service":"flint-api"}

curl -i -X POST https://YOUR-SERVICE.a.run.app/internal/check-alerts
#   401  ← correct: armed and refusing an unauthenticated caller
#   503  ← CRON_SECRET did not reach the service
```

In the deploy logs look for `Database schema is at head` and
`Application startup complete`.

**Continuous deploys (optional).** `cloudbuild.yaml` at the repo root builds,
pushes and deploys on a push. Cloud Build → Triggers → Create, point it at your
branch. It only ever replaces the image, so environment variables and secrets set
above are left alone.

## Step 4 — Frontend on Vercel

1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory: `frontend`.** This repo holds both halves, so the default
   (repo root) will not build.
3. Add the four frontend variables (ENVIRONMENT.md §5), ticking **Production,
   Preview and Development**. `NEXT_PUBLIC_API_URL` is the Cloud Run URL from
   step 3.
4. Deploy.

If a variable is missing the build **fails on purpose**, naming it. That beats
the alternative it replaced — a build that succeeded and then pointed every
visitor's browser at `localhost:8000`.

## Step 5 — Supabase Cron: the 15-minute tick

**Without this step rate alerts are never checked, and nothing reports that.**
The app has no other trigger.

1. Open `supabase/cron_check_alerts.sql` from this repo.
2. Replace the two placeholders: your **Cloud Run URL** and the **same
   `CRON_SECRET`** you put in Secret Manager.
3. Paste it into the Supabase **SQL Editor** and run it. It enables `pg_cron` and
   `pg_net`, stores the secret in **Vault** (not in the job body, which is
   readable), and schedules `*/15 * * * *`.

Confirm it registered, then force one tick rather than waiting:

```sql
select jobname, schedule, active from cron.job where jobname = 'vaulto-check-alerts';

-- the manual-tick query is at the bottom of the .sql file; then:
select status_code, content, created from net._http_response order by created desc limit 5;
```

`200` with `{"status":"completed", …}` is a working tick. `401` means the Vault
secret and `CRON_SECRET` disagree. `409` means a run was already going.

> Supabase's dashboard also has **Integrations → Cron**, which is a UI over the
> same `pg_cron`. The SQL file is the reproducible version; either works.

## Step 6 — Join it up

1. Put the real Vercel URL into the backend's `ALLOWED_ORIGINS` if you used a
   placeholder:
   ```bash
   gcloud run services update vaulto-api --region asia-south1 \
     --update-env-vars "ALLOWED_ORIGINS=https://your-app.vercel.app"
   ```
2. Put it into Supabase → **Authentication → URL Configuration**.
3. For Vercel preview deployments, whose hostnames are generated, add
   `ALLOWED_ORIGIN_REGEX` — ENVIRONMENT.md §3.

## Step 7 — Verify, in this order

1. `GET /health` → `{"status":"ok"}`
2. `GET /api/providers` → a list of 28
3. Open the site and run a comparison **signed out** — exercises frontend →
   backend and CORS.
4. **Sign up** with a real address. With Confirm email on you get a code; typing
   it and clicking the emailed link should both work.
5. You land on **/onboarding**, not /dashboard. Complete it.
6. Reload `/dashboard` — the profile persists, so the database write worked.
7. Visit `/settings` directly while signed out: it should bounce to `/auth` and
   then return you to `/settings`.
8. **The alert path, end to end.** Create a rate alert with a target the market
   has already passed, then fire a tick by hand (step 5) instead of waiting.
   Expect the email, and the alert to show as paused on `/alerts`. Needs
   `RESEND_API_KEY` and a verified sender domain.
9. Admin: put your Supabase user UUID in `ADMIN_USER_IDS` (Cloud Run) and
   `NEXT_PUBLIC_ADMIN_USER_IDS` (Vercel), redeploy both, open `/admin/analytics`.

## Step 8 — Custom domain (optional)

1. Vercel → Settings → **Domains** → add it, follow the DNS records.
2. Then update, or auth breaks confusingly:
   - Cloud Run `ALLOWED_ORIGINS` → add the new origin
   - Supabase **Site URL** and **Redirect URLs** → the new domain
   - Resend → verify the domain if you send alerts from it

---

## Troubleshooting

The symptom table at the end of **[ENVIRONMENT.md](ENVIRONMENT.md)** covers CORS,
the localhost bundle, `401`s, connection-string encoding, the
localhost-in-email problem and the cron statuses.

Cloud-Run-specific ones:

**Deploy fails: "The user-provided container failed to start and listen on the
port."** The container must listen on `$PORT`. `backend/Dockerfile` already does;
if you changed the `CMD`, keep `--port ${PORT}`. The real cause is more often the
startup crashing — read the logs:
```bash
gcloud run services logs read vaulto-api --region asia-south1 --limit 100
```
Usually `DATABASE_URL`: password not percent-encoded, or port 6543 not used.

**Alerts stopped and `net._http_response` shows nothing recent.** The cron job is
gone or paused: `select jobname, active from cron.job;`. Re-run step 5.

**`409` on every tick.** A run is taking longer than 15 minutes. Add
`REDIS_URL` if you have not (it caches the provider fan-out, which is nearly all
of the time), and check `--timeout` is not cutting runs off and leaving the lock
to expire.

**Migrating by hand**, if you would rather not migrate on boot:
```bash
cd backend && DATABASE_URL=… alembic upgrade head
```

---

## What is actually running

```
Browser
  │
  ├── Vercel ─────────── Next.js pages + middleware.js
  │                      (validates the Supabase session cookie on /dashboard,
  │                       /onboarding, /settings, /alerts, /history, /admin
  │                       before any HTML is sent)
  │
  ├── Supabase Auth ──── sign-in, sign-up, OAuth, password reset
  │                      (issues the JWT the browser sends onward)
  │
  └── Cloud Run ──────── FastAPI, scaled to zero when idle
                           ├── verifies that JWT against Supabase's JWKS
                           ├── Supabase Postgres (transaction pooler)
                           ├── Upstash Redis (optional: cache + run lock)
                           ├── 28 provider APIs
                           └── POST /internal/check-alerts
                                 ▲   └── check_alerts() → Resend
                                 │
                    Supabase pg_cron ─── every 15 min, bearing CRON_SECRET
```

Only the frontend is on Vercel. Everything holding a secret runs on Cloud Run,
which is why the `service_role` key never reaches a browser. Nothing schedules
work inside the API process, which is why it can scale to zero without losing
alerts.
