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
│   ├── schemas.py              # Pydantic models (shared data contract)
│   ├── money.py                # Decimal money core: exponents, half-up rounding
│   ├── delivery.py             # ISO-8601 / speed codes → minutes
│   ├── cache.py                # Redis, keyed on the EXACT amount
│   ├── requirements.txt
│   ├── .env.example
│   ├── providers/
│   │   ├── __init__.py         # Exports ALL_PROVIDERS list
│   │   ├── base.py             # Abstract BaseProvider + exact JSON decoding
│   │   ├── quote.py            # RawQuote + FeeModel (deducted vs added)
│   │   ├── wise.py             # Wise: /gateway/v3/comparisons
│   │   ├── remitly.py          # Remitly: /v3/calculator/estimate
│   │   └── western_union.py    # WU: /wuconnect/prices/catalog
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── normalize.py        # Re-base onto one basis + total cost
│   │   ├── ranking.py          # Sort modes + filters
│   │   └── comparator.py       # Concurrent fetch, normalize, filter, rank
│   └── tests/                  # 128 tests over recorded provider payloads
│
└── frontend/
    ├── next.config.js
    ├── package.json
    ├── .env.local.example
    ├── lib/
    │   └── api.js              # fetch wrapper for /compare
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

## Setup & Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
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

# Copy env file
cp .env.example .env

# Start the server
uvicorn main:app --reload --port 8000
```

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

# Copy env file
cp .env.local.example .env.local

# Start the dev server
npm run dev
```

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

128 tests covering Decimal precision and rounding, ISO-4217 minor units,
delivery parsing, fee-model re-basing, the five sort modes, the filters, and a
full three-provider comparison.

The provider tests run against **recorded payload shapes** in
`tests/fixtures.py`, driven through real HTTP plumbing with a mock transport.
They pin the parsing and the maths built on top of it. They do **not** prove
the upstream field names still match production — re-record them against live
responses before trusting a deploy.

---

## Deployment

### Backend (Railway / Render / Fly.io)

```bash
# Procfile
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set env var: `ALLOWED_ORIGINS=https://your-frontend.vercel.app`

### Frontend (Vercel)

```bash
vercel deploy
```

Set env var: `NEXT_PUBLIC_API_URL=https://your-backend.railway.app`

---

## Supported Currency Pairs

Any pair where all three providers operate. Best coverage for:

| Send | Receive |
|------|---------|
| USD | INR, PHP, MXN, BDT, PKR, NGN, KES, VND, THB, EUR, GBP |
| GBP | EUR, INR, USD, AUD |
| EUR | GBP, USD, INR |
| CAD | INR, PHP, USD |
| AUD | INR, PHP, USD |

---

## Limitations & Next Steps

- **Mid-market reference depends on Wise.** FX markup and `total_cost` are
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
