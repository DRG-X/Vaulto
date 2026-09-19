# ⚡ Flint — International Money Transfer Comparison Engine

Flint is a real-time comparison tool that fetches live quotes from **Wise**, **Remitly**, and **Western Union**, then tells you exactly which provider gives your recipient the most money.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (Next.js)                    │
│  ┌────────────┐  POST /compare  ┌────────────────────┐  │
│  │  Home Page │ ──────────────► │  FastAPI Backend   │  │
│  │  (form)    │ ◄────────────── │  main.py           │  │
│  └────────────┘  CompareResult  └────────┬───────────┘  │
└──────────────────────────────────────────┼──────────────┘
                                           │
                          ┌────────────────▼───────────────┐
                          │    engine/comparator.py        │
                          │  asyncio.gather() all providers│
                          └────────────────┬───────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
   ┌──────────▼──────────┐   ┌─────────────▼────────────┐  ┌────────────▼───────────┐
   │ engine/normalize.py │   │   engine/ranking.py      │  │      money.py          │
   │                     │   │                          │  │                        │
   │ Re-base every quote │   │ 5 sort modes + filters   │  │ Decimal everywhere,    │
   │ onto ONE basis:     │   │ cheapest / fastest /     │  │ ISO-4217 minor units,  │
   │ send_amount = what  │   │ lowest_fee / best_rate / │  │ half-up rounding       │
   │ leaves your account │   │ best_value               │  │                        │
   │                     │   │                          │  ├────────────────────────┤
   │ + FX markup vs      │   │ Picks WHICH option each  │  │     delivery.py        │
   │   mid-market        │   │ provider shows           │  │ ISO-8601 / speed codes │
   │ + true total cost   │   │                          │  │ → minutes              │
   └──────────┬──────────┘   └─────────────┬────────────┘  └────────────────────────┘
              │                            │
              └────────────┬───────────────┘
                           │  RawQuote (exact Decimals, declared fee model)
        ┌──────────────────┼──────────────────┐
        │                  │                  │
 ┌──────▼─────┐   ┌────────▼────┐   ┌─────────▼──────┐
 │  wise.py   │   │ remitly.py  │   │western_union.py│
 │            │   │             │   │                │
 │ /gateway/  │   │ /v3/        │   │ /wuconnect/    │
 │  v3/       │   │  calculator │   │  prices/       │
 │  comparisons│  │  /estimate  │   │  catalog       │
 │            │   │             │   │                │
 │ fee        │   │ fee ADDED   │   │ fee ADDED      │
 │  DEDUCTED  │   │ + solves for│   │ + solves for   │
 │ publishes  │   │ fee-inclusive│  │ fee-inclusive  │
 │ mid-market │   │ principal   │   │ principal      │
 └────────────┘   └─────────────┘   └────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **One comparable basis** | `send_amount` = what leaves your account, fee included. Wise deducts its fee from the amount you send; Remitly and WU charge it on top. Comparing their raw receive amounts compared a sender who spent 1000 with one who spent 1000+fee |
| **Decimal end to end** | Money is decimal, not binary. JSON is decoded with `parse_float=Decimal` so a provider's published rate never passes through a float |
| **Half-up rounding** | Python's `round()` is banker's rounding: `round(2.675, 2)` is 2.67, but providers quote 2.68 |
| **ISO-4217 minor units** | JPY has no decimal places, KWD has three. Rounding either to 2 dp invents or destroys precision |
| **Solve for the fee-inclusive principal** | Fee-on-top providers are re-quoted at `budget - fee` so their own tiered fee schedule produces the number, rather than us assuming the first tier holds |
| **Provider returns options, engine chooses** | Each provider publishes several pay-in/pay-out combinations. The engine picks the one matching the user's sort mode and filters, so a speed filter switches rails instead of dropping the provider |
| **Failures never enter the maths** | A provider that cannot quote is reported in `failed_providers`, not ranked with `receive_amount: 0` |
| **Concurrent provider fetches** | `asyncio.gather()` — total latency is the slowest provider, not the sum |
| **Markup omitted rather than guessed** | With no mid-market reference, markup is `null`. Deriving one from the best provider's own rate would show that provider a flattering 0% |
| **No mock data** | All data is fetched live; the app is honest about failures |

---

## Project Structure

```
flint/
├── backend/
│   ├── main.py                 # FastAPI app + CORS + routes
│   ├── auth.py                 # Supabase JWT verification (JWKS + legacy HS256)
│   ├── supabase_client.py      # Supabase Admin API — recovers a missing address
│   ├── database.py             # Supabase Postgres engine + session
│   ├── models.py               # SQLAlchemy tables, keyed on supabase_user_id
│   ├── alembic/                # Schema migrations, incl. the RLS lockdown
│   ├── scripts/
│   │   └── verify_providers.py # Check every provider against its live endpoint
│   ├── schemas.py              # Pydantic models (shared data contract)
│   ├── money.py                # Decimal money core: exponents, half-up rounding
│   ├── delivery.py             # ISO-8601 / speed codes → minutes
│   ├── cache.py                # Redis, keyed on the EXACT amount
│   ├── requirements.txt
│   ├── .env.example
│   ├── providers/
│   │   ├── registry.py         # ALL_PROVIDERS + corridor/credential selection
│   │   ├── meta.py             # Category, corridors, credentials, avoid flags
│   │   ├── base.py             # Abstract BaseProvider + exact JSON decoding
│   │   ├── quote.py            # RawQuote + FeeModel (deducted vs added)
│   │   ├── partner_base.py     # Shared plumbing for credential-gated APIs
│   │   ├── wise.py             # Wise: /gateway/v3/comparisons (both directions)
│   │   ├── remitly.py          # Remitly: /v3/calculator/estimate
│   │   ├── western_union.py    # WU: /wuconnect/prices/catalog
│   │   ├── xe.py               # XE: mid-market reference only
│   │   ├── ofx.py, instarem.py, airwallex.py, revolut.py
│   │   └── scrapers/
│   │       ├── sites.py        # 9 scrape providers as editable config rows
│   │       ├── engine.py       # One provider class, driven by SiteConfig
│   │       └── extract.py      # Rate extraction, fails rather than guesses
│   ├── engine/
│   │   ├── normalize.py        # Re-base onto one basis + total cost
│   │   ├── ranking.py          # Sort modes + filters
│   │   ├── sanity.py           # Reject rates that cannot be right
│   │   └── comparator.py       # Select, fetch, normalize, filter, rank
│   └── tests/                  # 358 tests
│
└── frontend/
    ├── next.config.js
    ├── package.json
    ├── .env.example
    ├── middleware.js           # Supabase session refresh + protected routes
    ├── contexts/
    │   └── AuthContext.js      # useAuth() / useUser() over supabase-js
    ├── lib/
    │   ├── supabase.js         # Cookie-backed browser client (@supabase/ssr)
    │   └── api.js              # fetch wrapper, sends the access token
    ├── styles/
    │   └── globals.css         # Full design system (dark terminal aesthetic)
    ├── components/
    │   ├── BestProviderCard.js # Hero card for the winning provider
    │   └── ComparisonTable.js  # Full ranked table
    └── pages/
        ├── _app.js
        └── index.js            # Home + results (single page)
```

---

## Supabase (database + auth)

Both halves of the backend live in one Supabase project: Postgres holds the
tables, and Supabase Auth issues the sessions. There is no separate auth
vendor and no separate database host.

### Create the project

1. Create a project at [supabase.com](https://supabase.com) and note the
   database password — it appears once.
2. **Project Settings → API** gives you three values:
   - `Project URL` → `SUPABASE_URL` (backend) and `NEXT_PUBLIC_SUPABASE_URL`
   - `anon` / publishable key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (**backend only**)
3. **Project Settings → Database → Connection string → URI** gives the two
   Postgres URLs. Use the **transaction pooler** (port 6543) for
   `DATABASE_URL`, and the **session pooler** (port 5432) for `DIRECT_URL`.

`service_role` bypasses Row Level Security completely. It belongs in the
backend's environment and nowhere else — never in a `NEXT_PUBLIC_` variable,
never in the browser bundle.

### Which key goes where

| Key | Where it lives | What it can do |
|---|---|---|
| `anon` / publishable | Browser bundle, by design | Sign in, sign up, refresh a session. Reaches no app table — RLS denies it |
| `service_role` | Backend environment only | Everything, RLS included. Used solely to read an address out of `auth.users` when an alert fires |
| Postgres connection string | Backend environment only | The API's own connection; it owns the tables, so RLS does not apply to it |

### Create the schema

Alembic owns the schema — not the Supabase dashboard, and not
`supabase db push`. Point it at the project and run it:

```bash
cd backend
export DATABASE_URL='postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres'
export DIRECT_URL='postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres'
alembic upgrade head
```

`DIRECT_URL` matters here: migrations run their DDL inside a single
transaction, and the transaction pooler can hand consecutive statements to
different backends. The API itself is stateless and is happy on the pooler.

The app also runs `alembic upgrade head` on startup (`main.run_migrations`),
so a deploy migrates itself. Running it by hand first is how you see the
output.

### Row Level Security

Supabase publishes every table in `public` through PostgREST, reachable with
the anon key that ships in the frontend bundle. A table with RLS **disabled**
is therefore world-readable and world-writable.

Migration `c3f8a1d47e60` enables RLS on `users`, `comparisons`, `rate_alerts`
and `provider_clicks`, and revokes the `anon` and `authenticated` grants. With
no policies attached, PostgREST can reach none of them. The API is unaffected:
it connects as the table owner, and owners bypass RLS.

Every read and write still goes through FastAPI, which authorises it against
the `sub` of a verified token. If you later add a policy to let the browser
query a table directly, scope it to `auth.uid()` — a policy added for one
table does not re-open the others.

### Auth configuration

**Authentication → URL Configuration:**

- *Site URL* — `http://localhost:3000` in development, your Vercel URL in
  production.
- *Redirect URLs* — add `http://localhost:3000/**` and
  `https://your-app.vercel.app/**`. Supabase refuses to redirect anywhere not
  on this list, and OAuth fails with a bare "redirect not allowed" until the
  callback is there.

**Authentication → Providers → Google:** enable it and paste the client ID and
secret from the Google Cloud console. The authorised redirect URI Google needs
is `https://your-project-ref.supabase.co/auth/v1/callback` — Supabase's own
URL, not this app's.

**Authentication → Providers → Email:** "Confirm email" is on by default. The
sign-up form handles that: it tells the user to check their inbox rather than
pretending they are signed in. Turn it off for faster local testing.

### How a request is authenticated

1. The browser signs in through `supabase-js`, which stores the session **in
   cookies** (`@supabase/ssr`'s `createBrowserClient`) so `middleware.js` can
   see it server-side.
2. `contexts/AuthContext.js` exposes `useAuth()` / `useUser()`, and
   `getToken()` returns a fresh access token, refreshing it when it is close
   to expiry.
3. `lib/api.js` sends it as `Authorization: Bearer <token>`.
4. `backend/auth.py` verifies the signature, the issuer and the audience, then
   hands the route `{user_id, email, full_name}`. `user_id` is the UUID from
   `auth.users` and the only thing any query filters on.

Signature verification follows the token's own `alg` header: HS256 against
`SUPABASE_JWT_SECRET` (legacy projects), anything asymmetric against the
project's JWKS. A project rotating from one to the other needs no redeploy.

### Migrating from Clerk

Existing rows keep their old Clerk ids in the renamed `supabase_user_id`
column — nothing is deleted, but those ids match no Supabase user, so the
history attached to them will not appear for the re-registered account. To
carry it across, sign the user up in Supabase and re-point the rows:

```sql
UPDATE users SET supabase_user_id = '<new-uuid>' WHERE supabase_user_id = 'user_oldClerkId';
```

The foreign keys are `ON UPDATE NO ACTION`, so update the child tables
(`comparisons`, `rate_alerts`, `provider_clicks`) in the same transaction.

---

## Setup & Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Supabase project (see the section above) — or nothing at all, if you are
  happy with the SQLite fallback and no sign-in
- (Optional) Chromium — only needed if provider APIs are blocked and Playwright fallbacks trigger

---

### 1. Backend (FastAPI)

```bash
cd flint/backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (only needed for scraping fallback)
playwright install chromium

# Copy env file and fill in the Supabase values
cp .env.example .env

# Create the schema in Supabase (skip to use the SQLite fallback)
alembic upgrade head

# Start the server
uvicorn main:app --reload --port 8000
```

With `DATABASE_URL` unset the backend falls back to `sqlite:///./flint.db`,
which is enough to work on the comparison engine. Anything behind a login
needs the Supabase values.

The API will be live at: **http://localhost:8000**

Verify it works:
```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"flint-api"}
```

Test a comparison:
```bash
curl -X POST http://localhost:8000/compare \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000, "currency_from": "USD", "currency_to": "INR"}'
```

---

### 2. Frontend (Next.js)

```bash
cd flint/frontend

# Install dependencies
npm install

# Copy env file and fill in the Supabase values
cp .env.example .env.local

# Start the dev server
npm run dev
```

`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are required —
without them every page that touches auth throws on load.

The app will be live at: **http://localhost:3000**

---

### 3. Running Both Together (quick script)

From the repo root:

```bash
# Terminal 1 — Backend
cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

---

## API Reference

### `POST /compare`

**Request body:**
```json
{
  "amount": 1000,
  "currency_from": "USD",
  "currency_to": "INR",

  "sort_by": "cheapest",
  "max_eta_minutes": null,
  "pay_in_method": null,
  "pay_out_method": null,
  "include_promo": true
}
```

Only `amount`, `currency_from` and `currency_to` are required; the rest default
to the values shown.

| Field | Meaning |
|---|---|
| `sort_by` | `cheapest` (default, most money received) · `fastest` · `lowest_fee` · `best_rate` (smallest FX markup) · `best_value` (cost and speed blended) |
| `max_eta_minutes` | Drop quotes that cannot arrive this fast. `60` = "within the hour" |
| `pay_in_method` | Funding rail, e.g. `BANK`, `DEBIT`, `CREDIT` |
| `pay_out_method` | Delivery rail, e.g. `BANK_DEPOSIT`, `CASH_PICKUP`, `UPI` |
| `include_promo` | `false` excludes first-transfer promotional rates, which a returning customer cannot get |

**Response:**
```json
{
  "best_provider": { "...one of quotes..." },
  "quotes": [
    {
      "provider": "Wise",
      "send_amount": 1000.00,
      "fee": 5.46,
      "exchange_rate": 83.4210,
      "receive_amount": 82965.87,
      "currency_from": "USD",
      "currency_to": "INR",
      "transfer_time": "1-20 hours (Bank Transfer)",

      "exchange_rate_exact": "83.421",
      "receive_amount_exact": "82965.87",

      "eta_min_minutes": 60,
      "eta_max_minutes": 1200,
      "eta_is_business_days": false,

      "mid_market_rate": 83.4210,
      "fx_markup_pct": 0.0,
      "fx_markup_cost": 0.0,
      "total_cost": 5.46,
      "total_cost_pct": 0.546,

      "fee_model": "deducted",
      "principal_amount": 994.54,
      "normalized": false,
      "pay_in_method": "BANK_TRANSFER",
      "pay_out_method": "BANK_TRANSFER",
      "is_promotional": false,
      "rate_type": "base"
    }
  ],
  "savings_vs_worst": 280.54,
  "savings_vs_average": 175.93,
  "best_by": {
    "cheapest": "Wise", "fastest": "Western Union", "lowest_fee": "Remitly",
    "best_rate": "Wise", "best_value": "Wise"
  },
  "mid_market_rate": 83.4210,
  "mid_market_source": "Wise",
  "errors": [],
  "filtered_out": [],
  "request": { "..." },
  "failed_providers": []
}
```

Everything above `exchange_rate_exact` is the original response contract and is
unchanged. The rest is additive.

**Reading the new fields:**

* **`send_amount` is fee-inclusive.** It is what leaves the sender's account.
  `principal_amount + fee == send_amount` holds for every provider — that
  invariant is what makes `receive_amount` comparable between them.
* **`total_cost` is the real price**, not `fee`. A provider advertising no fee
  usually recovers it in the exchange rate; `total_cost = fee + fx_markup_cost`
  exposes that. Ranking on `fee` alone is what `lowest_fee` is for, and it is
  deliberately a different answer from `cheapest`.
* **`*_exact` fields** carry the full-precision decimal as a string, for
  clients that must not inherit float rounding.
* **`normalized: true`** means the engine re-based this quote rather than using
  the provider's own published receive amount.
* **`fx_markup_pct` is `null`** when no mid-market reference was available.

### `GET /api/providers`

The registry as data — every provider the engine knows about, with its
category, corridors, transfer limits and integration type. The frontend
directory and the alert provider picker both read from it, so neither can
drift from what the engine actually compares.

```bash
curl "http://localhost:8000/api/providers?corridor=AUD:INR"
```

Benchmark-only providers are excluded and counted separately in
`hidden_benchmark`, so the omission reads as deliberate. Credential **names**
are exposed (`requires_credentials`) so a client can say what is missing;
their values never are.

### `GET /api/rates`

The same comparison as a GET, for the results page. Takes `from`, `to`,
`amount`, plus the five filter parameters above as query strings.

```bash
curl "http://localhost:8000/api/rates?from=USD&to=INR&amount=1000&sort_by=fastest&max_eta_minutes=60"
```

Responses are cached in Redis against the **exact** amount and the exact filter
combination.

---

## Adding a New Provider

1. Create `backend/providers/yourprovider.py`
2. Subclass `BaseProvider` and implement `fetch_raw_quote()`, returning a `RawQuote`
3. Add it to `ALL_PROVIDERS` in `backend/providers/__init__.py`

The comparator picks it up automatically. Two things matter more than the rest:

**Declare your fee model honestly.** `FeeModel.DEDUCTED` means the fee comes
out of the amount the sender hands over (Wise). `FeeModel.ADDED` means it is
charged on top (Remitly, Western Union). Get this wrong and the provider will
be systematically over- or under-stated against every other one.

**Do not do comparison maths.** Return the provider's own numbers as exact
Decimals and let `engine/normalize.py` re-base them. Decode JSON with
`decode_json_exact()` so rates never pass through a float.

```python
# providers/yourprovider.py
from decimal import Decimal

import delivery
from money import D
from providers.base import BaseProvider, decode_json_exact
from providers.quote import FeeModel, RawQuote


class YourProvider(BaseProvider):
    name = "YourProvider"

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(..., params={"amount": str(amount)})
            resp.raise_for_status()
            data = decode_json_exact(resp)      # Decimals, not floats

        eta_min, eta_max = delivery.parse_wise_estimation(data["eta"])

        return RawQuote(
            provider=self.name,
            currency_from=currency_from,
            currency_to=currency_to,
            principal=amount,                   # what THIS provider converts
            fee=D(data["fee"]),
            fee_model=FeeModel.ADDED,           # be sure about this
            exchange_rate=D(data["rate"]),
            receive_amount=D(data["receive"], default=None),
            eta_min_minutes=eta_min,
            eta_max_minutes=eta_max,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
        )
```

Return a `RawQuote` carrying an `error` rather than raising — one provider's
outage should never end the comparison.

---

## Tests

```bash
cd backend && python -m pytest tests/ -q
```

358 tests covering Decimal precision and rounding, ISO-4217 minor units,
delivery parsing, fee-model re-basing, the five sort modes, the filters, a
full three-provider comparison, and token verification — including the tokens
that only look valid, such as another project's or the anon key itself.

The provider tests run against **recorded payload shapes** in
`tests/fixtures.py`, driven through real HTTP plumbing with a mock transport.
They pin the parsing and the maths built on top of it. They do **not** prove
the upstream field names still match production — re-record them against live
responses before trusting a deploy.

---

## Deployment

### Database + auth (Supabase)

Managed — nothing to deploy. Point the backend at the project and it migrates
itself on startup. See [Supabase (database + auth)](#supabase-database--auth).

### Backend (Render / Fly.io / Railway / anywhere that runs a container)

```bash
# Procfile
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Required environment:

```
DATABASE_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
DIRECT_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key>
ALLOWED_ORIGINS=https://your-frontend.vercel.app
ADMIN_USER_IDS=<comma-separated Supabase user UUIDs>
```

Add `SUPABASE_JWT_SECRET` only if the project still signs tokens with the
legacy shared secret.

### Frontend (Vercel)

```bash
vercel deploy
```

Required environment:

```
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
NEXT_PUBLIC_API_URL=https://your-backend.example.com
NEXT_PUBLIC_ADMIN_USER_IDS=<comma-separated Supabase user UUIDs>
```

Then add the deployed origin to Supabase's **Authentication → URL
Configuration → Redirect URLs**, or OAuth will refuse to come back to it.

---

## Providers

**28 providers** — every row of the provider master list, across both
directions of the AUD ↔ INR corridor. ("Wise India" is not separate: it is the
Wise integration with the direction reversed.)

### Send AUD → INR (19 providers)

| Provider | Pri | Integration | Limits | Notes |
|---|---|---|---|---|
| Wise | 1 | Public API | A$1–1M | Quotes at mid-market |
| Remitly | 1 | Public API | A$10–30k | Base rate preferred over promo |
| XE | 1 | Partner API | — | **Reference only** |
| Western Union | 2 | Public API | A$1–50k | Uses the PRICECATALOG JSON |
| OFX | 2 | Partner API | A$200+ | Fee-free above A$200 |
| InstaReM | 2 | Partner API | A$1–500k | Zero-fee model |
| Airwallex | 2 | Partner API | A$1+ | Two-step auth, token cached |
| Revolut | 2 | Partial API | A$1+ | Weekend surcharge modelled |
| CurrencyFair | 3 | Partner API | A$8–150k | P2P — **can beat mid-market** |
| WorldRemit | 3 | Partner API | A$1–9k | UPI payout to India |
| TorFX | 3 | Partner API | **A$2,000+** | Broker; endpoint via env |
| Moneycorp | 4 | Partner API | **A$1,000+** | Broker; endpoint via env |
| SingX | 4 | Partial API | A$200–500k | |
| CommBank | 1 | Scrape | A$1+ | `avoid` |
| ANZ · Westpac | 2 | Scrape | A$1+ | `avoid` |
| NAB | 3 | Scrape | A$1+ | `avoid` |
| MoneyGram | 3 | Scrape | A$1–10k | **JS calculator** |
| Panda Remit | 3 | Scrape | A$10–50k | **JS calculator** |

### Send INR → AUD (11 providers)

| Provider | Pri | Integration | Limits | Notes |
|---|---|---|---|---|
| Wise | 1 | Public API | — | Same integration, reversed |
| XE | 1 | Partner API | — | **Reference only** |
| SBI | 1 | Scrape | ₹1,000+ | `avoid` |
| HDFC · ICICI | 2 | Scrape | ₹1,000+ | `avoid` |
| BookMyForex | 2 | Scrape | ₹1,000–15L | The realistic India-side benchmark |
| ExTravelMoney | 2 | Scrape | ₹500–10L | |
| HOP Remit | 2 | Scrape | ₹1,000+ | **Benchmark only — never displayed** |
| Niyo Global | 3 | Partial API | ₹1,000+ | Popular with students |
| Axis Forex | 3 | Scrape | ₹5,000+ | `avoid` |
| Thomas Cook India | 3 | Scrape | ₹5,000–15L | |

### Five things worth knowing

**Transfer limits are enforced before any call.** Brokers offer their best
rates precisely *because* they refuse small transfers — TorFX starts at
A$2,000, Moneycorp at A$1,000. Without the floors, a student sending A$500
would see TorFX win with a quote TorFX would decline. Limits are only applied
when the send currency matches the currency they are denominated in; comparing
A$2,000 to a rupee amount needs a rate we do not have at selection time, and a
wrong conversion would hide a real option.

**Only Wise can originate rupees.** Moving money *out* of India requires an RBI
AD-II licence under the Liberalised Remittance Scheme. The global fintechs and
brokers receive rupees; they do not send them. They are excluded from INR→AUD
via `cannot_send_from`, so they are never called there rather than failing
confusingly. Wise is the exception — it runs an Indian entity, which is what
the sheet lists separately as "Wise India".

**"USD 250,000 LRS" is not a per-transfer cap.** It is India's *annual*
per-person allowance, denominated in a third currency. Modelling it as a
maximum would wrongly exclude large legitimate transfers, so LRS-capped
providers carry no `max_amount`.

**XE is a reference, not a quote.** `xecdapi.xe.com` is XE's *currency-data*
product: it returns mid-market, not XE Money Transfer's retail pricing.
Ranking it as a quote would show a flat 0% markup and win every comparison at
a price nobody can buy. As the neutral reference it is worth more — markup no
longer depends on a competitor (Wise) being reachable.

**CurrencyFair can legitimately beat mid-market.** It is peer-to-peer: a
matched trade can settle better than interbank mid, giving a *negative*
`fx_markup_pct`. That is real, not a parsing error, and is reported as-is.

---

## Frontend

The comparison UI reads every field the engine produces. Four decisions shape it.

**True cost is the headline, not the fee.** Each provider card leads with a
two-part bar: the upfront fee in blue, the markup hidden in the exchange rate
in amber. A bank advertising A$0 and taking 1.6% in the rate reads as what it
is. The pair was validated for colour-vision separation against the card
surface (ΔE 26.3 protan, 32.0 normal) and both segments are direct-labelled,
so the reading never rests on colour alone.

**Sorting and filtering happen on the server.** Changing sort re-queries rather
than reordering rows in place, because the backend picks *which of a
provider's rails to quote* per mode — asking for "fastest" switches Remitly
from bank deposit (3–5 days) to UPI (minutes), and "lowest fee" switches
Western Union to its A$0 bank row. Re-sorting in the browser cannot do that,
and would disagree with the badges the backend computed.

**The banks show real quotes.** The results page used to render a hardcoded
panel of invented figures ("Rate: ~52–54 INR per AUD (estimated)"). Those are
gone. Banks are live quotes on the same fee-inclusive basis as everything
else, carrying the backend's own `avoid` flag, collapsed behind a toggle that
names the actual gap.

**Rate alerts watch what they name.** An alert scoped to a provider (or a
delivery rail) now watches *that* quote, not whichever provider happens to be
cheapest. It reads the full option pool rather than the ranked comparison,
because ranking collapses each provider to one rail — a "Remitly via UPI"
alert looking at the ranked output would only ever see Remitly's bank row.

**"Not shown" is three different things.** Providers that don't serve the
corridor, need an API key, or fall outside their transfer limits appear under
"N more providers not shown" with the real reason. Providers your filter
excluded are listed separately. Only genuine failures are surfaced as errors.
Collapsing those into one "couldn't fetch rates" list makes a healthy system
look broken and buries the one provider that really did fail.

### Where things live

```
frontend/
├── lib/
│   ├── api.js            # Filter params; SORT_MODES
│   ├── format.js         # Money at real currency precision, ETA, rails, cost split
│   └── providerMeta.js   # Outbound links, icons, category colours for all 28
├── components/
│   ├── CostBar.js        # Fee vs hidden markup, the headline
│   ├── ProviderCard.js   # One quote, with a detail drawer of exact values
│   ├── SortBar.js        # Five modes, each naming its winner up front
│   ├── FilterPanel.js    # Speed, payout rail, funding rail, promos
│   └── ProviderStatus.js # Unavailable / filtered / failed, kept distinct
└── pages/results.js      # Server-side sort + filters in the URL
```

A null field renders as "—", never as zero. `fx_markup_pct: null` means no
mid-market reference was available, which is a different statement from "0%
markup" — and printing 0% would flatter whichever provider happened to be
listed.

---

## Configuring partner APIs

Five providers need credentials you apply for. Without them they are skipped
cleanly — nothing fails. Add to `backend/.env`:

```bash
# Priority 1-2
XE_ACCOUNT_ID=...          # xecdapi.xe.com — supplies the mid-market reference
XE_API_KEY=...
OFX_API_KEY=...            # ofx.com/en-au/business/api
INSTAREM_API_KEY=...       # partnerships@instarem.com
AIRWALLEX_CLIENT_ID=...    # developer.airwallex.com
AIRWALLEX_API_KEY=...
REVOLUT_API_KEY=...        # developer.revolut.com

# Priority 3-4
CURRENCYFAIR_API_KEY=...   # help.currencyfair.com/api
WORLDREMIT_API_KEY=...     # partnerships@worldremit.com
SINGX_API_KEY=...          # singx.co
MONEYCORP_API_KEY=...      # moneycorp.com/api

# TorFX and Niyo Global publish no endpoint at all ("contact us"), so the URL
# comes from your partner agreement. A hard-coded guess would 404 and read as
# an outage rather than as "you have not been onboarded yet".
TORFX_API_KEY=...
TORFX_API_URL=...
NIYO_API_KEY=...
NIYO_API_URL=...
```

Every provider above is skipped cleanly when its credentials are absent —
nothing fails, and `unavailable_providers` says exactly what is missing.

---

## ⚠️ Verify before you deploy

The 25 providers added from the master list were written against published
documentation and the usual shape of bank rate pages. **None could be tested
against a live response** — the environment they were written in
blocks every provider host at the network policy level. The API field names
and, especially, the HTML selectors in `providers/scrapers/sites.py` are
informed guesses.

Run this from a network that can reach them:

```bash
cd backend
python -m scripts.verify_providers --corridor AUD:INR --amount 1000
python -m scripts.verify_providers --corridor INR:AUD --amount 100000
```

Each provider reports one of:

| Status | Meaning |
|---|---|
| `OK` | A plausible quote came back — still spot-check the numbers |
| `NO KEY` | Credentials not configured; nothing to test yet |
| `N/A` | Does not serve this corridor or this amount (expected) |
| `NEEDS JS` | Rate is behind a JavaScript calculator — needs its JSON endpoint or Playwright, **not** a selector fix |
| `BROKEN` | Reached it and could not parse the answer — this is the one to fix |

Exit status is non-zero if anything is `BROKEN`, so it can gate a deploy.

A `BROKEN` scraper is almost always a selector: open the page, find the column
that actually holds the telegraphic-transfer rate, and edit `sites.py`. That
is a data change, not a code change — which is why the nine scrapers are one
engine and nine rows of config rather than nine classes.

**A parse that succeeds can still read the wrong column,** so spot-check the
numbers against each provider's own site. Two guards limit the damage in the
meantime:

* Scrapers that cannot find a rate return an error. They never guess, and
  never fall back to a stale constant — a wrong bank rate would rank a bank as
  the best deal, the exact opposite of why those providers are here.
* `engine/sanity.py` rejects any rate more than 25% from the corridor
  consensus. That catches the dangerous failure: six India-side scrapers must
  invert their rate card (`"AUD 57.50"` means one dollar costs 57.50 rupees),
  and an inversion done backwards is ~3,300x too good and would win
  everything. Real spreads are a few percent, so the band cannot reject an
  honest quote.

---

## Adding another provider

Every row of the master list is already integrated. For anything new:

* **Scrape-based** — add a `SiteConfig` row to `providers/scrapers/sites.py`.
  No code. Set `quotes_target_in_source=True` if the page prices one unit of
  the receive currency in the send currency (the Indian rate-card convention),
  and `requires_js=True` if the rate only appears after JavaScript runs.
* **API-based** — subclass `PartnerAPIProvider`, implement `_build_request`
  and `_parse`, and register it in `providers/registry.py`. Set `DEFAULT_URL`
  if the endpoint is published and `URL_ENV` if it is not.

Either way, fill in `ProviderMeta` honestly: the corridors it serves, the
transfer band, whether it can originate the send currency, and its category.
The registry uses all of it to decide whether the provider is worth calling.

---

## Limitations & Next Steps

- **Above A$1,000,000 there is no mid-market reference without XE.** Wise's
  transfer ceiling is A$1M, so past it Wise is correctly excluded — and with
  it goes the fallback reference, leaving only the banks and no markup
  reported. Configuring `XE_ACCOUNT_ID` / `XE_API_KEY` fixes this completely:
  a data feed has no transfer limit and is never excluded on amount. Left as
  a documented gap rather than special-cased, since transfers of that size are
  well outside the student-remittance corridor this is built for.
- **MoneyGram and Panda Remit are registered but not fetched.** Their rates
  live behind JavaScript calculators, so they are reported as unavailable with
  what they need rather than being called on every comparison for a guaranteed
  timeout. Finding the JSON endpoint their calculator calls — as the Western
  Union provider does — turns either into a working API provider.
- **Mid-market reference otherwise depends on Wise.** FX markup and `total_cost` are
  measured against the mid-market rate Wise publishes in its comparison
  payload. If that endpoint is unavailable or drops the field, markup comes
  back `null` for the whole comparison rather than being guessed. A dedicated
  FX feed would make markup independent of any provider being up.
- **Business days are stored as calendar minutes.** A "2-3 business days"
  quote becomes 2880-4320 minutes so speeds are orderable. That is exact
  enough to rank and filter on, but it does not know about weekends or
  holidays. `eta_is_business_days` records which quotes were quoted that way.
- **Fee refinement costs one extra request.** Fee-on-top providers are
  re-quoted at the corrected principal. Providers run concurrently so this
  adds one round-trip, not one per provider.
- **Promotional rates are excluded from ranking by default** (`base_rate` is
  preferred) but surfaced via `is_promotional`. First-transfer pricing is real
  money, just not repeatable.
- **More providers:** Xoom, OFX, Xe, CurrencyFair, Instarem, Panda Remit all
  have reachable public pricing endpoints.
- **Send-from country:** MVP infers it from the source currency. EUR defaults
  to Germany, which is not right for every EUR sender.
- **Historical tracking:** Store quotes over time to show rate trends.

---

*Flint is not affiliated with Wise, Remitly, or Western Union. Rates shown are indicative and fetched in real time.*
