"""
XEProvider — XE Currency Data API (xecdapi.xe.com).

Reference-only, deliberately.
-----------------------------
The provider sheet lists XE as a Critical integration, and it is — but not as
a quote. `xecdapi.xe.com` is XE's CURRENCY DATA product: it returns the
mid-market rate. XE Money Transfer's retail pricing (the rate you would
actually be sold, with XE's margin inside it) is a different product behind a
different agreement, and this endpoint does not expose it.

Ranking the mid-market rate as "XE's quote" would be the same class of error
this engine was just fixed for: it would show XE at a flat 0% markup, beating
every provider on `best_rate` and usually on `cheapest`, at a price no
customer can buy.

So XE is wired in as what it genuinely is — the mid-market REFERENCE that
every other provider's markup is measured against. That is worth having on its
own: it removes the engine's dependency on Wise being reachable for markup to
be computable, and it is a more neutral yardstick than any provider's own rate.

To promote XE to a ranked provider, add XE Money Transfer's retail quote
endpoint here and drop `rate_reference_only` from the metadata. The rest of
the pipeline needs no changes.

Auth: HTTP Basic — account ID as username, API key as password.
Docs:  https://xecdapi.xe.com
"""

from __future__ import annotations

import base64
import logging
import os
from decimal import Decimal

import httpx

from money import D, ZERO
from providers.base import BaseProvider, decode_json_exact
from providers.meta import Category, Integration, ProviderMeta
from providers.quote import RawQuote

logger = logging.getLogger(__name__)


class XEProvider(BaseProvider):
    name = "XE"

    BASE_URL = "https://xecdapi.xe.com/v1/convert_from.json"

    meta = ProviderMeta(
        name="XE",
        category=Category.FINTECH,
        integration=Integration.PARTNER_API,
        priority=1,
        credentials=("XE_ACCOUNT_ID", "XE_API_KEY"),
        rate_reference_only=True,
        website="https://xecdapi.xe.com",
        notes=(
            "Currency-data API — supplies the mid-market reference rate. "
            "Not a retail quote; see module docstring."
        ),
    )

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        account = (os.getenv("XE_ACCOUNT_ID") or "").strip()
        api_key = (os.getenv("XE_API_KEY") or "").strip()
        if not account or not api_key:
            return self._error(
                currency_from, currency_to,
                "XE not configured — set XE_ACCOUNT_ID and XE_API_KEY",
            )

        token = base64.b64encode(f"{account}:{api_key}".encode()).decode()

        try:
            async with httpx.AsyncClient(
                timeout=15,
                headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
            ) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "from": currency_from.upper(),
                        "to": currency_to.upper(),
                        "amount": str(amount),
                    },
                )
                resp.raise_for_status()
                data = decode_json_exact(resp)
        except Exception as e:
            return self._error(currency_from, currency_to, f"XE API error: {e}")

        rate = self._extract_rate(data, currency_to)
        if not rate or rate <= ZERO:
            return self._error(
                currency_from, currency_to,
                f"XE returned no rate for {currency_from}->{currency_to}",
            )

        logger.info("[XE] mid-market reference %s %s->%s", rate, currency_from, currency_to)

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            exchange_rate=rate,
            mid_market_rate=rate,
            reference_only=True,
            rate_type="mid_market",
        )

    @staticmethod
    def _extract_rate(data: dict, currency_to: str):
        """
        Read the quote currency out of XE's `to` list.

        The payload is `{"from": "AUD", "amount": 1000, "to": [{"quotecurrency":
        "INR", "mid": 54.12, "amount": 54120.0}]}`. We take `mid` — the rate —
        rather than `amount`, so the value does not depend on the amount we
        happened to ask about.
        """
        entries = data.get("to")
        if not isinstance(entries, list):
            return None

        wanted = currency_to.upper()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("quotecurrency", "")).upper() != wanted:
                continue
            rate = D(entry.get("mid"), default=None)
            if rate and rate > ZERO:
                return rate
        return None
