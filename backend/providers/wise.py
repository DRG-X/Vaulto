"""
WiseProvider — Wise's public comparison gateway.

Endpoint: GET https://wise.com/gateway/v3/comparisons

What changed and why
--------------------
* Numbers are decoded with `parse_float=Decimal`, so Wise's published rate
  arrives with the digits Wise actually sent instead of the nearest binary
  float.

* We no longer take `quotes[0]`. That array holds one entry per
  pay-in/pay-out combination, in no guaranteed order, so the old code compared
  whichever combination happened to be first — sometimes a card-funded quote
  against a rival's bank-funded one. Every combination is now returned as an
  option and the engine picks the one that fits the user's filter.

* Wise's fee is DEDUCTED from the amount you send: you hand over `sendAmount`,
  Wise takes `fee` out of it and converts the rest. Declaring that lets the
  engine stop comparing it against fee-on-top providers as if the two meant
  the same thing.

* Wise quotes at the mid-market rate, and the payload carries it explicitly.
  That is the reference every other provider's markup is measured against, so
  we surface it rather than throwing it away.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

import httpx

import delivery
from money import D, ZERO
from providers.base import BaseProvider, decode_json_exact
from providers.meta import Category, Integration, ProviderMeta
from providers.quote import FeeModel, RawQuote

logger = logging.getLogger(__name__)


class WiseProvider(BaseProvider):
    name = "Wise"

    #: One integration covers both directions. "Wise India" on the provider
    #: sheet is this same endpoint with source and target reversed, so it needs
    #: no separate provider — only the corridor rule below, which already
    #: admits INR->AUD.
    meta = ProviderMeta(
        name="Wise",
        category=Category.FINTECH,
        integration=Integration.PUBLIC_API,
        priority=1,
        website="https://wise.com",
        notes="Quotes at mid-market; supplies the reference rate for markup.",
    )

    COMPARISONS_URL = "https://wise.com/gateway/v3/comparisons"
    LIVE_RATE_URL = "https://wise.com/rates/live"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    #: Pay-in methods, cheapest/most comparable first. A bank-funded transfer
    #: is the like-for-like basis every comparison site uses as its default;
    #: card funding carries an acquiring fee that is not really an FX cost.
    PAY_IN_PREFERENCE = ["BANK_TRANSFER", "DIRECT_DEBIT", "SWIFT", "DEBIT_CARD", "CREDIT_CARD"]

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        async with httpx.AsyncClient(timeout=15, headers=self.HEADERS) as client:
            try:
                return await self._from_comparisons(client, amount, currency_from, currency_to)
            except Exception as primary_err:
                logger.warning("[Wise] comparisons failed (%s) — trying live rate", primary_err)
                try:
                    return await self._from_live_rate(client, amount, currency_from, currency_to)
                except Exception as fallback_err:
                    return self._error(
                        currency_from, currency_to,
                        f"Primary: {primary_err} | Fallback: {fallback_err}",
                    )

    # ------------------------------------------------------------------ #
    #  Primary: /gateway/v3/comparisons
    # ------------------------------------------------------------------ #

    async def _from_comparisons(
        self,
        client: httpx.AsyncClient,
        amount: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        resp = await client.get(
            self.COMPARISONS_URL,
            params={
                "sourceCurrency": currency_from.upper(),
                "targetCurrency": currency_to.upper(),
                "sendAmount": str(amount),   # str keeps 1000.50 from becoming 1000.5000000001
            },
        )
        resp.raise_for_status()
        data = decode_json_exact(resp)

        mid_rate = self._extract_mid_market(data)

        wise_entry = next(
            (p for p in data.get("providers", []) if str(p.get("alias", "")).lower() == "wise"),
            None,
        )
        if not wise_entry or not wise_entry.get("quotes"):
            raise ValueError("Wise entry absent from comparisons response")

        options: List[RawQuote] = []
        for q in wise_entry["quotes"]:
            option = self._build_option(q, amount, currency_from, currency_to, mid_rate)
            if option is not None:
                options.append(option)

        if not options:
            raise ValueError("Wise returned no usable quote rows")

        options.sort(key=self._preference_key)

        primary = options[0]
        primary.options = options
        return primary

    def _build_option(
        self,
        q: dict,
        amount: Decimal,
        currency_from: str,
        currency_to: str,
        mid_rate: Optional[Decimal],
    ) -> Optional[RawQuote]:
        rate = D(q.get("rate"))
        if rate <= ZERO:
            return None

        fee = D(q.get("fee"))
        received = D(q.get("receivedAmount"), default=None)

        eta_min, eta_max = delivery.parse_wise_estimation(q.get("deliveryEstimation") or {})

        # Wise deducts its fee from the amount handed over, so the converted
        # principal is what is left of `amount` after the fee.
        principal = amount - fee

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=principal,
            fee=fee,
            fee_model=FeeModel.DEDUCTED,
            exchange_rate=rate,
            receive_amount=received if received and received > ZERO else None,
            eta_min_minutes=eta_min,
            eta_max_minutes=eta_max,
            eta_is_business_days=False,
            pay_in_method=_upper(q.get("sourcePaymentMethod")),
            pay_out_method=_upper(q.get("targetPaymentMethod")),
            mid_market_rate=mid_rate,
            rate_type="base",
        )

    def _preference_key(self, option: RawQuote):
        """Bank-funded first, then cheapest fee — the like-for-like default."""
        method = option.pay_in_method or ""
        try:
            rank = self.PAY_IN_PREFERENCE.index(method)
        except ValueError:
            rank = len(self.PAY_IN_PREFERENCE)
        return (rank, option.fee, option.provider)

    @staticmethod
    def _extract_mid_market(data: dict) -> Optional[Decimal]:
        """
        Pull the mid-market rate out of the comparisons payload.

        Wise has moved this key around across revisions, so we check the
        shapes it has used rather than betting on one. If none is present we
        return None and the engine simply does not report markup — a wrong
        reference is worse than no reference, because it would misstate every
        provider's true cost.
        """
        for key in ("midMarketRate", "midRate", "sourceTargetMidMarketRate"):
            value = D(data.get(key), default=None)
            if value and value > ZERO:
                return value

        nested = data.get("rate")
        if isinstance(nested, dict):
            value = D(nested.get("value") or nested.get("midMarketRate"), default=None)
            if value and value > ZERO:
                return value
        return None

    # ------------------------------------------------------------------ #
    #  Fallback: /rates/live — mid-market rate only
    # ------------------------------------------------------------------ #

    async def _from_live_rate(
        self,
        client: httpx.AsyncClient,
        amount: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        """
        Last resort when the comparison gateway is unreachable.

        This endpoint gives the mid-market rate and nothing else, so the fee
        is an ESTIMATE. It is flagged as such in `rate_type` and the ETA is
        left unknown rather than guessed — an invented delivery time would
        silently win a "fastest" ranking it has no claim to.
        """
        resp = await client.get(
            self.LIVE_RATE_URL,
            params={"source": currency_from.upper(), "target": currency_to.upper()},
        )
        resp.raise_for_status()
        data = decode_json_exact(resp)

        rate = D(data.get("value"))
        if rate <= ZERO:
            raise ValueError("live rate endpoint returned no usable rate")

        # Wise's published pricing for major corridors sits near 0.65%.
        estimated_fee = amount * Decimal("0.0065")

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount - estimated_fee,
            fee=estimated_fee,
            fee_model=FeeModel.DEDUCTED,
            exchange_rate=rate,
            receive_amount=None,          # let the engine derive it
            mid_market_rate=rate,         # Wise quotes at mid-market
            rate_type="estimated",
        )


def _upper(value) -> Optional[str]:
    return str(value).strip().upper() if value else None
