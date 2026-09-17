"""
AirwallexProvider — Airwallex live FX rates.

Airwallex is two-step: exchange the client ID and API key for a short-lived
bearer token, then quote with it. The token is cached in-process for its
lifetime so a burst of comparisons does not re-authenticate on every call.

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://developer.airwallex.com
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from money import D, ZERO
from providers.base import decode_json_exact
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider, DEFAULT_HEADERS
from providers.quote import FeeModel, RawQuote

logger = logging.getLogger(__name__)

#: Airwallex settles bank-to-bank; same-day to two days on AU->IN.
ETA_MIN_MINUTES = 1440
ETA_MAX_MINUTES = 2880

#: Refresh the token this many seconds before it actually expires, so a quote
#: never starts with a token that dies mid-flight.
TOKEN_SAFETY_MARGIN = 60


class AirwallexProvider(PartnerAPIProvider):
    name = "Airwallex"

    #: The token for the request currently being built. A ContextVar rather
    #: than an attribute because concurrent tasks share this singleton and
    #: would otherwise clobber each other's value between auth and request.
    _pending_token: contextvars.ContextVar = contextvars.ContextVar(
        "airwallex_token", default=None
    )

    AUTH_URL = "https://api.airwallex.com/api/v1/authentication/login"
    RATE_URL = "https://api.airwallex.com/api/v1/fx/rates/current"

    meta = ProviderMeta(
        name="Airwallex",
        category=Category.FINTECH,
        integration=Integration.PARTNER_API,
        priority=2,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        credentials=("AIRWALLEX_CLIENT_ID", "AIRWALLEX_API_KEY"),
        min_amount=Decimal('1'),
        max_amount=None,
        limits_currency="AUD",
        website="https://developer.airwallex.com",
        notes="Two-step auth; token cached in-process.",
    )

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        # Providers are module-level singletons and the comparator fans out
        # concurrently, so an expiring token would otherwise send every
        # in-flight request to authenticate at once.
        self._token_lock = asyncio.Lock()

    async def _access_token(self) -> str:
        """Return a valid bearer token, re-authenticating only when needed."""
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        async with self._token_lock:
            # Re-check inside the lock: whoever held it first has probably
            # already refreshed, and a second round-trip would immediately
            # invalidate the token they just fetched.
            now = time.time()
            if self._token and now < self._token_expires_at:
                return self._token
            return await self._authenticate(now)

    async def _authenticate(self, now: float) -> str:
        creds = self.credentials()
        async with httpx.AsyncClient(timeout=self.TIMEOUT, headers=DEFAULT_HEADERS) as client:
            resp = await client.post(
                self.AUTH_URL,
                headers={
                    "x-client-id": creds["AIRWALLEX_CLIENT_ID"],
                    "x-api-key": creds["AIRWALLEX_API_KEY"],
                },
            )
            resp.raise_for_status()
            data = decode_json_exact(resp)

        token = self.first(data, "token", "access_token")
        if not token:
            raise ValueError("Airwallex authentication returned no token")

        # Airwallex tokens are short-lived (~30 min). Treat an unknown
        # lifetime conservatively rather than caching indefinitely.
        expires_in = float(D(self.first(data, "expires_in"), default=Decimal("1800")))
        self._token = str(token)
        self._token_expires_at = now + max(0.0, expires_in - TOKEN_SAFETY_MARGIN)
        return self._token

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        missing = self._missing()
        if missing:
            return self._error(
                currency_from, currency_to,
                f"Airwallex not configured — set {', '.join(missing)}",
            )

        try:
            token = await self._access_token()
        except Exception as e:
            # Invalidate so the next attempt re-authenticates rather than
            # reusing a token we no longer trust.
            async with self._token_lock:
                self._token, self._token_expires_at = None, 0.0
            return self._error(currency_from, currency_to, f"Airwallex auth failed: {e}")

        # Passed through the call rather than stored on self: this provider is
        # a shared singleton, and stashing per-request state on it means two
        # concurrent corridors can overwrite each other's token.
        self._pending_token.set(token)
        try:
            return await super().fetch_raw_quote(amount, currency_from, currency_to)
        finally:
            self._pending_token.set(None)

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "GET",
            "url": self.RATE_URL,
            "headers": {"Authorization": f"Bearer {self._pending_token.get()}"},
            "params": {
                "sell_currency": currency_from.upper(),
                "buy_currency": currency_to.upper(),
                "sell_amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        payload = self.first(data, "items.0", default=data)
        if isinstance(data, dict) and isinstance(data.get("items"), list) and data["items"]:
            payload = data["items"][0]

        rate = D(self.first(payload, "rate", "client_rate", "buy_rate"), default=None)
        if not rate or rate <= ZERO:
            return None

        mid = D(self.first(payload, "mid_rate", "market_rate"), default=None)

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=D(self.first(payload, "fee", "total_fee"), default=ZERO) or ZERO,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(self.first(payload, "buy_amount"), default=None),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            mid_market_rate=mid if mid and mid > ZERO else None,
        )
