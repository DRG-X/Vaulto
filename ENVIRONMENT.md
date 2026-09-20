# Environment variables — every key, and where to get it

Two `.env` files, and they are not interchangeable. Putting a backend secret in
the frontend file publishes it to every visitor.

| | file | goes to |
|---|---|---|
| **Frontend** | `frontend/.env.local` | Vercel → Project → Settings → Environment Variables |
| **Backend** | `backend/.env` | your backend host's environment settings (Render / Railway / Fly) |

Templates to copy: `frontend/.env.example` and `backend/.env.example`.
Both `.env` files are gitignored. Keep it that way — if a key ever lands in a
commit, rotate it rather than deleting the commit.

> **Note on Supabase dashboard labels.** Supabase renamed some pages in 2025.
> Where the old label differs it is given second, like
> **Project Settings → API Keys** *(older projects: Project Settings → API)*.

---

## 1. Frontend — 4 variables

Every name starts with `NEXT_PUBLIC_`, which in Next.js means **compiled into
the JavaScript bundle that every visitor downloads**. Two consequences:

- Nothing secret can go here. The three values below are all safe to publish.
- They are read at **build** time, not run time. Changing one in the Vercel
  dashboard does nothing until you **redeploy**.

### `NEXT_PUBLIC_SUPABASE_URL`
Your project's base URL, e.g. `https://abcdefghijkl.supabase.co`.

> Supabase dashboard → your project → **Project Settings** (gear, bottom left)
> → **Data API** *(older projects: **API**)* → **Project URL** → Copy.

No trailing slash.

### `NEXT_PUBLIC_SUPABASE_ANON_KEY`
The public key the browser authenticates with.

> **Project Settings → API Keys** → the key labelled **`anon` / `public`**
> (newer projects call it the **publishable key**, and it starts `sb_publishable_`)
> → Copy.

This one is *designed* to be public. Row Level Security is what limits it —
which the migration `c3f8a1d47e60` already enabled on every app table.

⚠️ Do **not** put the `service_role` / `secret` key here. It bypasses RLS
entirely, and in this file it would be handed to every visitor.

### `NEXT_PUBLIC_API_URL`
The public URL of your deployed backend, e.g.
`https://vaulto-api.onrender.com`. No trailing slash.

> You get this **after** deploying the backend (step 3 of DEPLOYMENT.md). On
> Render it is shown at the top of the service page.

Must be `https://` in production: an HTTPS page is not permitted to call an
HTTP address, and the browser blocks it as mixed content. `next build` refuses
to produce a production bundle when this is missing or plaintext HTTP — that
check exists because the old default was `http://localhost:8000`, which built
fine and then made every visitor's browser call their own machine.

### `NEXT_PUBLIC_ADMIN_USER_IDS` *(optional)*
Comma-separated Supabase user UUIDs that see the admin links.

> **Authentication → Users** → click your user → copy the **UID**.

Only shows or hides UI. The real gate is `ADMIN_USER_IDS` on the backend,
checked against the signed token — so leaving this blank costs you nothing but
a menu item, and filling it in grants nobody anything.

---

## 2. Backend — the 5 that are required

### `DATABASE_URL`  — **required**
The connection this API serves requests on. Use the **transaction pooler**,
port **6543**.

> **Project Settings → Database → Connection string** → **URI** tab →
> the **Transaction pooler** entry → Copy, then replace `[YOUR-PASSWORD]` with
> your database password.

```
postgresql://postgres.PROJECTREF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
```

- **Lost the password?** Project Settings → Database → **Reset database
  password**. It is shown once.
- **Special characters in the password** must be percent-encoded: `@` → `%40`,
  `#` → `%23`, `/` → `%2F`, `:` → `%3A`. A raw `@` splits the URL in the wrong
  place and you get a confusing "could not translate host name" error.
- Port **5432** (direct) is IPv6-only on Supabase unless you have bought the
  IPv4 add-on, which is why the pooler is the right default.

### `DIRECT_URL`  — strongly recommended
The same database over the **session pooler**, port **5432**. Only Alembic uses
it. Migrations run DDL inside one transaction and need a single backend, which
the transaction pooler cannot promise.

> Same dashboard page, the **Session pooler** entry.

Leave it unset and migrations run over `DATABASE_URL`, which usually works but
can fail in ways that are unpleasant to debug mid-deploy.

### `SUPABASE_URL`  — **required**
Same value as `NEXT_PUBLIC_SUPABASE_URL`. The backend needs its own copy
because it verifies the token issuer against it — without that pin, a correctly
signed token from *someone else's* Supabase project would be accepted.

### `SUPABASE_SERVICE_ROLE_KEY`  — **required**
> **Project Settings → API Keys** → **`service_role`** *(newer projects: the
> **secret key**, starting `sb_secret_`)* → **Reveal** → Copy.

🔴 **Server-side only.** This key bypasses Row Level Security completely —
it can read and write every row in your database. Never put it in
`frontend/.env.local`, never commit it, never paste it into a browser console.

Used for one thing: reading a user's email out of `auth.users` when a rate alert
fires and the local row has no address on file.

### `ADMIN_USER_IDS`  — **required to use the admin pages**
Comma-separated Supabase user UUIDs. This is the enforcing list.

> **Authentication → Users** → your user → **UID**.

Empty means *nobody* is an admin; `/api/admin/*` returns 403 for everyone.
That is the safe default, not a bug.

### `SUPABASE_JWT_SECRET`  — only for older projects
> **Project Settings → API Keys → JWT Keys** *(older: API → JWT Settings)* →
> **JWT Secret** → Reveal → Copy.

Only needed while your project still signs tokens with the **legacy shared
HS256 secret**. Projects on asymmetric **JWT signing keys** need nothing here:
the backend discovers the public keys from `SUPABASE_URL` and verifies against
the JWKS.

**Which do you have?** Look at **Project Settings → API Keys → JWT Keys**. If
it shows a *signing key* with an algorithm like ES256/RS256, leave
`SUPABASE_JWT_SECRET` blank. If it shows only a *JWT secret*, set it. Setting
it when it is not needed is harmless; the token's own `alg` header decides which
path is used, so both work at once during a rotation.

---

## 3. Backend — CORS

### `ALLOWED_ORIGINS`  — **required in production**
Comma-separated list of frontend origins allowed to call this API.

```
ALLOWED_ORIGINS=https://vaulto.vercel.app,https://www.yourdomain.com
```

Scheme + host (+ port) only. **No trailing slash, no path.** An `Origin` header
never contains a path, so `https://app.com/` matches nothing.

Get this wrong and the symptom misleads you: the API answers with a normal 200,
the browser discards the response for lacking the header, and the frontend
reports a generic network error. Check the API logs on boot — it prints
`CORS allowed origins: [...]` with exactly what it parsed.

### `ALLOWED_ORIGIN_REGEX`  — optional
For Vercel **preview** deployments, whose hostname contains the branch name and
so cannot be listed ahead of time:

```
ALLOWED_ORIGIN_REGEX=https://vaulto-[a-z0-9-]+\.vercel\.app
```

Skip it if you only care about production. Make it specific — a regex like
`.*\.vercel\.app` lets anyone's Vercel project call your API with credentials.

---

## 4. Backend — optional extras

Everything below can be left unset. The app runs correctly without all of it.

### `REDIS_URL` — caching
Must be the **Redis-protocol** URL (`redis://`, or `rediss://` for TLS).

> [Upstash](https://console.upstash.com) → Create Database (pick the region
> nearest your backend) → the database page → **Connect** → the **redis-cli**
> or **ioredis** tab → copy the `rediss://default:PASSWORD@HOST:6379` string.

Two traps:
- Upstash also shows `UPSTASH_REDIS_REST_URL` / `..._REST_TOKEN`. Those are for
  a **different client** and are ignored here. The app now logs a warning
  naming this exact mistake, because configuring them looks like it worked.
- Use the read-**write** token. A read-only one has a username ending `_ro`,
  and every cache write fails.

Without it: every comparison re-quotes all 28 providers. Correct, just slower.

### `RATE_CACHE_TTL_SECONDS` — default `300`
How long a cached comparison stays fresh.

### `RESEND_API_KEY` + `ALERT_FROM_EMAIL` — rate-alert email
Without these, rate alerts are still evaluated and stored but no email is sent.

> [resend.com/api-keys](https://resend.com/api-keys) → **Create API Key**
> (starts `re_`). Free tier: 3,000/month, **100/day** — the daily cap is the
> one that limits how many alerts can fire.

`ALERT_FROM_EMAIL` must be on a domain you have verified in Resend
(**Domains → Add Domain**, then add the DKIM/SPF records). Until the domain is
verified Resend rejects every send with a 403.

Leave `ALERT_FROM_EMAIL` unset and it falls back to Resend's
`onboarding@resend.dev`, which needs no domain setup but **only delivers to the
Resend account owner's own address** — enough to prove the pipeline works, not
enough to serve users.

### `PGSSLMODE` — default `require`
Supabase requires TLS. Only set this (to `disable`) for a plaintext local
Postgres.

### Provider API keys — all optional
**17 of the 28 providers work with no credentials at all**, so the comparison is
useful out of the box. The other 11 sit behind keys you have to apply for, and
each is simply reported as "not configured" until its key is present:

`AIRWALLEX_CLIENT_ID` · `AIRWALLEX_API_KEY` · `CURRENCYFAIR_API_KEY` ·
`INSTAREM_API_KEY` · `MONEYCORP_API_KEY` · `NIYO_API_KEY` + `NIYO_API_URL` ·
`OFX_API_KEY` · `REVOLUT_API_KEY` · `SINGX_API_KEY` ·
`TORFX_API_KEY` + `TORFX_API_URL` · `WORLDREMIT_API_KEY` ·
`XE_ACCOUNT_ID` + `XE_API_KEY`

Niyo and TorFX publish no documented endpoint, so their `_API_URL` is required
alongside the key — the URL comes from your partner agreement.

### `PORT`
Set by Render / Railway / Fly automatically. **Do not set it yourself.**

---

## 5. Copy-paste checklists

**Vercel** → Project → Settings → Environment Variables (tick Production,
Preview *and* Development):

```
NEXT_PUBLIC_SUPABASE_URL=https://YOURREF.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon / publishable key>
NEXT_PUBLIC_API_URL=https://<your-backend-host>
NEXT_PUBLIC_ADMIN_USER_IDS=<your user UUID>
```

**Backend host** → Environment:

```
DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
DIRECT_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
SUPABASE_URL=https://YOURREF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role / secret key>
ADMIN_USER_IDS=<your user UUID>
ALLOWED_ORIGINS=https://your-app.vercel.app
# optional
REDIS_URL=rediss://default:PASSWORD@HOST:6379
RESEND_API_KEY=re_...
ALERT_FROM_EMAIL=Vaulto Alerts <alerts@yourdomain.com>
SUPABASE_JWT_SECRET=<only if your project has no JWT signing keys>
```

## 6. When something is wrong

| Symptom | Almost always |
|---|---|
| Build fails: "these environment variables are not set" | Add them in Vercel, then **redeploy** — a build-time value cannot be patched in afterwards |
| Every API call fails, console says CORS | `ALLOWED_ORIGINS` missing your Vercel URL, or has a trailing slash / stray space |
| Calls go to `localhost:8000` from the live site | `NEXT_PUBLIC_API_URL` was unset **at build time**; set it and redeploy |
| `401` on every authenticated call | `SUPABASE_URL` on the backend does not match the project the frontend signs in to |
| Backend won't start, "could not translate host name" | Password not percent-encoded in `DATABASE_URL`, or `[YOUR-PASSWORD]` never replaced |
| Sign-up email link goes to `localhost:3000` | Supabase **Authentication → URL Configuration → Site URL** still points at localhost |
| Logs say "caching disabled" | `REDIS_URL` unset, or you set the Upstash **REST** pair instead |
| Alerts never arrive | No `RESEND_API_KEY`, unverified sender domain, or the backend is on a free tier that sleeps |
