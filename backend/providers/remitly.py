"""
RemitlyProvider — Remitly's internal calculator API.

Endpoint: GET https://api.remitly.io/v3/calculator/estimate
Conduit format: "{SRC_ISO3}:{SRC_CCY}-{DST_ISO3}:{DST_CCY}", e.g. "USA:USD-IND:INR".

What changed and why
--------------------
* Remitly charges its fee ON TOP of the amount converted: ask to send 1000 and
  you pay 1000+fee while the recipient gets 1000*rate. The old code reported
  that `1000 * rate` straight against Wise's `(1000 - fee) * rate`, which
  compared a sender who spent 1000+fee with one who spent 1000. On a USD->INR
  transfer that handed Remitly a few hundred rupees it had not earned — small
  enough to look like a rounding bug, big enough to pick the wrong winner.
  The provider now declares `FeeModel.ADDED` and lets the engine re-base it.

* Rather than only inferring the re-based figure arithmetically, we ask
  Remitly directly. Their fees are TIERED, so the fee on a 1000 principal is
  not always the fee on a 996.01 principal, and a transfer sitting near a tier
  boundary would otherwise be quoted with the wrong fee. A second call at the
  corrected principal gets the real number from the source; see
  `_quote_fee_inclusive`.

* All numeric fields are parsed from Remitly's own decimal STRINGS via
  `D()`. They were previously run through `float()`, which discarded the exact
  value Remitly published before any maths happened.

* Delivery speed now comes back as structured minutes instead of a label, so
  it can actually be ranked and filtered.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import List, Optional

import httpx

from money import D, ZERO, floor_money
from providers.base import BaseProvider, decode_json_exact
from providers.meta import Category, Integration, ProviderMeta
from providers.quote import FeeModel, RawQuote

logger = logging.getLogger(__name__)


def _block(est: dict, key: str) -> dict:
    """
    Read a nested object from an estimate, tolerating an explicit JSON null.

    `est.get("fee", {})` returns None — not {} — when the payload contains
    `"fee": null`, and the chained `.get()` then raises AttributeError. That
    escapes to the catch-all in `fetch_raw_quote` and drops Remitly out of the
    comparison entirely over one null field.
    """
    value = est.get(key)
    return value if isinstance(value, dict) else {}


class RemitlyUnsupportedCorridor(Exception):
    """Remitly returned 400 — this currency pair is not offered."""


class RemitlyProvider(BaseProvider):
    name = "Remitly"

    meta = ProviderMeta(
        name="Remitly",
        category=Category.FINTECH,
        integration=Integration.PUBLIC_API,
        priority=1,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        # Remitly caps outbound transfers at A$30,000.
        min_amount=Decimal('10'),
        max_amount=Decimal('30000'),
        limits_currency="AUD",
        website="https://www.remitly.com",
        notes="Calculator API is public; partner API would add richer data.",
    )

    ESTIMATE_URL = "https://api.remitly.io/v3/calculator/estimate"

    #: How many times we re-ask Remitly at a corrected principal before
    #: settling. Fees converge on the first correction in practice; the cap
    #: stops a pathological tier boundary from oscillating into a request loop.
    MAX_FEE_REFINEMENTS = 2

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://www.remitly.com",
        "Referer": "https://www.remitly.com/",
    }

    CURRENCY_TO_COUNTRY_ISO3 = {
        # Source countries
        "USD": "USA", "GBP": "GBR", "EUR": "DEU", "CAD": "CAN", "AUD": "AUS",
        "NZD": "NZL", "SGD": "SGP", "NOK": "NOR", "SEK": "SWE", "DKK": "DNK",
        "CHF": "CHE", "HKD": "HKG", "JPY": "JPN",
        # Destination countries
        "INR": "IND", "PHP": "PHL", "MXN": "MEX", "NGN": "NGA", "KES": "KEN",
        "PKR": "PAK", "BDT": "BGD", "LKR": "LKA", "NPR": "NPL", "VND": "VNM",
        "BRL": "BRA", "COP": "COL", "PEN": "PER", "GHS": "GHA", "ZAR": "ZAF",
        "THB": "THA", "IDR": "IDN", "MYR": "MYS", "CNY": "CHN", "KRW": "KOR",
        "EGP": "EGY", "MAD": "MAR", "TZS": "TZA", "UGX": "UGA", "RWF": "RWA",
        "ETB": "ETH", "XOF": "SEN", "GTQ": "GTM", "HNL": "HND", "DOP": "DOM",
        "JMD": "JAM", "HTG": "HTI", "CRC": "CRI", "NIO": "NIC", "SVC": "SLV",
        "BZD": "BLZ", "GYD": "GUY", "TTD": "TTO", "PLN": "POL", "RON": "ROU",
        "UAH": "UKR", "GEL": "GEO", "TRY": "TUR",
    }

    #: Pay-in method -> how long the money takes to settle, in minutes.
    #: Card funding clears instantly; bank debit waits on ACH.
    #: (min, max, quoted_in_business_days)
    PAY_IN_SPEED = {
        "DEBIT":     (0, 15, False),
        "CREDIT":    (0, 15, False),
        "APPLE_PAY": (0, 15, False),
        "PAYTO":     (0, 15, False),
        "BANK":      (3 * 1440, 5 * 1440, True),
        "ACH":       (3 * 1440, 5 * 1440, True),
    }
    DEFAULT_SPEED = (3 * 1440, 5 * 1440, True)

    #: Payout rails in preference order. Bank deposit is the like-for-like
    #: default every comparison site uses; cash pickup and card push carry
    #: costs that are not really FX costs.
    PAYOUT_PREFERENCE = [
        "BANK_DEPOSIT", "UPI", "DIRECT_TO_PHONE",
        "PUSH_TO_CARD", "HOME_DELIVERY", "CASH_PICKUP",
    ]

    # ------------------------------------------------------------------ #
    #  Public interface
    # ------------------------------------------------------------------ #

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        src = self.CURRENCY_TO_COUNTRY_ISO3.get(currency_from.upper())
        dst = self.CURRENCY_TO_COUNTRY_ISO3.get(currency_to.upper())

        if not src or not dst:
            missing = []
            if not src:
                missing.append(f"source={currency_from}")
            if not dst:
                missing.append(f"destination={currency_to}")
            return self._error(
                currency_from, currency_to,
                f"Unsupported corridor: no country mapping for {', '.join(missing)}",
            )

        conduit = f"{src}:{currency_from.upper()}-{dst}:{currency_to.upper()}"

        try:
            return await self._quote_fee_inclusive(conduit, amount, currency_from, currency_to)
        except RemitlyUnsupportedCorridor:
            return self._error(
                currency_from, currency_to,
                f"Corridor not supported by Remitly: {conduit}",
            )
        except Exception as e:
            return self._error(currency_from, currency_to, f"Remitly API error: {e}")

    # ------------------------------------------------------------------ #
    #  Fee-inclusive quoting
    # ------------------------------------------------------------------ #

    async def _quote_fee_inclusive(
        self,
        conduit: str,
        budget: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        """
        Quote the largest principal whose principal + fee fits inside `budget`.

        Remitly's API anchors on the principal (the amount converted), but the
        user's real constraint is their total outlay. So we solve for it:

            ask for `budget`            -> learn fee f1
            ask for `budget - f1`       -> learn fee f2
            if f2 == f1 we have converged: principal + fee == budget exactly.

        The loop matters because Remitly's fees are tiered. A 1000 USD budget
        with a 3.99 fee needs a 996.01 principal, and if 996.01 falls in a
        cheaper tier the fee changes, which changes the principal. Re-asking
        gets the true number instead of assuming the first tier holds.
        """
        principal = budget
        last_payload = None
        last_fee = None

        for attempt in range(self.MAX_FEE_REFINEMENTS + 1):
            payload = await self._request_with_retry({
                "conduit": conduit,
                "anchor": "SEND",
                "amount": str(principal),
                "customer_segment": "STANDARD",
                "customer_recognition": "UNRECOGNIZED",
                "strict_promo": "false",
            })
            last_payload = payload

            estimates = self._collect_estimates(payload)
            if not estimates:
                raise ValueError("Remitly returned no estimates")

            fee = self._best_fee(estimates, currency_from)

            if last_fee is not None and fee == last_fee:
                break   # converged: this principal's fee is stable

            target = floor_money(budget - fee, currency_from)
            if target <= ZERO:
                raise ValueError(
                    f"Remitly fee of {fee} {currency_from} exceeds the {budget} being sent"
                )

            last_fee = fee
            if target == principal:
                break   # already quoting the right principal

            if attempt == self.MAX_FEE_REFINEMENTS:
                # Out of refinements. Keep the last payload; the engine still
                # re-bases arithmetically, which is correct to within a tier.
                logger.info(
                    "[Remitly] fee did not converge for %s (last fee=%s) — "
                    "engine will re-base arithmetically", conduit, fee,
                )
                break

            principal = target

        return self._build_quote(last_payload, principal, currency_from, currency_to)

    def _best_fee(self, estimates: List[dict], currency_from: str) -> Decimal:
        """The fee on the option we would actually select."""
        chosen = min(estimates, key=self._estimate_sort_key)
        return D(_block(chosen, "fee").get("total_fee_amount"))

    # ------------------------------------------------------------------ #
    #  HTTP
    # ------------------------------------------------------------------ #

    async def _request_with_retry(self, params: dict, max_retries: int = 3) -> dict:
        """
        GET the estimate endpoint, backing off on 429.

        A 400 means the corridor does not exist and will never succeed, so it
        raises immediately rather than burning retries on it.
        """
        async with httpx.AsyncClient(timeout=15, headers=self.HEADERS) as client:
            last_exc: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    resp = await client.get(self.ESTIMATE_URL, params=params)

                    if resp.status_code == 400:
                        raise RemitlyUnsupportedCorridor(params.get("conduit", ""))

                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning(
                            "[Remitly] rate limited, retrying in %ss (%d/%d)",
                            wait, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(wait)
                        continue

                    resp.raise_for_status()
                    return decode_json_exact(resp)

                except (RemitlyUnsupportedCorridor, httpx.HTTPStatusError):
                    raise
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)

            raise last_exc or RuntimeError("Remitly: all retries exhausted")

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _collect_estimates(data: dict) -> List[dict]:
        """Flatten the headline estimate and every payout variant into one list."""
        estimates: List[dict] = []

        top = data.get("estimate")
        if top:
            estimates.append(top)

        block = data.get("pay_out_price_estimates")
        if isinstance(block, dict):
            estimates.extend(block.get("estimates") or [])

        return estimates

    def _estimate_sort_key(self, est: dict):
        """Preferred payout rail first, then cheapest fee."""
        method = str(est.get("pay_out_method") or "")
        try:
            rank = self.PAYOUT_PREFERENCE.index(method)
        except ValueError:
            rank = len(self.PAYOUT_PREFERENCE)
        return (rank, D(_block(est, "fee").get("total_fee_amount")), method)

    def _build_quote(
        self,
        data: dict,
        principal: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        estimates = self._collect_estimates(data)
        if not estimates:
            return self._error(currency_from, currency_to, "Remitly returned empty estimate data")

        estimates.sort(key=self._estimate_sort_key)

        options = [
            self._build_option(est, principal, currency_from, currency_to)
            for est in estimates
        ]
        options = [o for o in options if o is not None]

        if not options:
            return self._error(currency_from, currency_to, "Remitly returned no usable estimate")

        primary = options[0]
        primary.options = options
        return primary

    def _build_option(
        self,
        est: dict,
        principal: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> Optional[RawQuote]:
        rates = _block(est, "exchange_rate")
        base_rate = D(rates.get("base_rate"), default=None)
        promo_rate = D(rates.get("promotional_exchange_rate"), default=None)

        # Prefer the base rate: promotional rates are first-transfer-only, so
        # ranking on one tells a returning customer a price they cannot get.
        # The promo is still reported via `is_promotional` / `rate_type` so a
        # caller can choose to surface it.
        rate = base_rate if base_rate and base_rate > ZERO else promo_rate
        if not rate or rate <= ZERO:
            return None

        # True only when we are actually REPORTING a promotional rate, which
        # happens when Remitly published no base rate to fall back on.
        #
        # The earlier form of this check (`promo != base and rate == promo`)
        # could never fire: preferring the base rate above means `rate` equals
        # `base_rate` whenever one exists, so requiring both `rate == promo`
        # and `promo != base` was a contradiction. The flag was permanently
        # False, which silently made `include_promo=False` a no-op and let a
        # first-transfer-only price be quoted as the ongoing one.
        using_promo = bool(promo_rate) and rate == promo_rate
        has_base = bool(base_rate) and base_rate > ZERO
        is_promo = using_promo and not has_base

        fee = D(_block(est, "fee").get("total_fee_amount"))
        pay_in = str(est.get("pay_in_method") or "BANK").upper()
        pay_out = str(est.get("pay_out_method") or "").upper() or None

        eta_min, eta_max, business = self.PAY_IN_SPEED.get(pay_in, self.DEFAULT_SPEED)

        # Remitly's own receive figure is only usable when it was computed at
        # the same principal AND the same rate we are reporting. When we fell
        # back to the base rate but Remitly quoted the promo, its figure
        # describes a different price, so we let the engine derive ours.
        api_receive = D(est.get("receive_amount"), default=None)
        usable_receive = (
            api_receive
            if api_receive and api_receive > ZERO and not (promo_rate and rate != promo_rate)
            else None
        )

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=principal,
            fee=fee,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=usable_receive,
            eta_min_minutes=eta_min,
            eta_max_minutes=eta_max,
            eta_is_business_days=business,
            pay_in_method=pay_in,
            pay_out_method=pay_out,
            is_promotional=is_promo,
            rate_type="promotional" if is_promo else "base",
        )
