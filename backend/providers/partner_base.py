"""
providers/partner_base.py — shared plumbing for credential-gated partner APIs.

OFX, InstaReM, Airwallex and Revolut all work the same way: you apply for
partner access, you get credentials, and until then the endpoint is simply
closed to you. That is not an outage, and the registry already keeps them out
of a comparison when their keys are absent — this base class is the second
line of defence for when one is called directly.

⚠️  UNVERIFIED AGAINST LIVE ENDPOINTS
    The request shapes and response field names below are built from each
    provider's published documentation, not from captured responses. This
    session could not reach any provider host (egress policy). Before trusting
    these in production, run `python -m scripts.verify_providers` with real
    credentials on an unblocked network and correct whatever it reports.
    Each subclass names the fields it depends on so the fix is localized.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

import httpx

from providers.base import BaseProvider, decode_json_exact
from providers.quote import RawQuote

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Vaulto/1.0 (+https://github.com/DRG-X/Vaulto)",
}


class PartnerAPIProvider(BaseProvider):
    """
    A provider whose pricing sits behind credentials you have to apply for.

    Subclasses implement `_build_request()` and `_parse()`; everything else —
    credential checks, transport, error containment — is handled here.
    """

    TIMEOUT = 15

    def credentials(self) -> Dict[str, str]:
        """Current values of every credential this provider declares."""
        return {
            name: (os.getenv(name) or "").strip()
            for name in self.meta.credentials
        }

    def _missing(self) -> Sequence[str]:
        return [name for name, value in self.credentials().items() if not value]

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        missing = self._missing()
        if missing:
            return self._error(
                currency_from, currency_to,
                f"{self.name} not configured — set {', '.join(missing)}",
            )

        try:
            request = self._build_request(amount, currency_from, currency_to)
        except Exception as e:
            return self._error(currency_from, currency_to, f"{self.name} request error: {e}")

        try:
            async with httpx.AsyncClient(
                timeout=self.TIMEOUT,
                headers={**DEFAULT_HEADERS, **request.get("headers", {})},
            ) as client:
                resp = await client.request(
                    request.get("method", "GET"),
                    request["url"],
                    params=request.get("params"),
                    json=request.get("json"),
                )
                resp.raise_for_status()
                data = decode_json_exact(resp)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            # 401/403 almost always means the key is wrong or the partner
            # application has not been approved — worth saying plainly rather
            # than reporting it as a generic outage.
            if status in (401, 403):
                return self._error(
                    currency_from, currency_to,
                    f"{self.name} rejected the credentials ({status}) — "
                    f"check {', '.join(self.meta.credentials)} and that partner access is approved",
                )
            return self._error(currency_from, currency_to, f"{self.name} HTTP {status}")
        except Exception as e:
            return self._error(currency_from, currency_to, f"{self.name} API error: {e}")

        try:
            quote = self._parse(data, amount, currency_from, currency_to)
        except Exception as e:
            logger.exception("[%s] parse failed", self.name)
            return self._error(
                currency_from, currency_to,
                f"{self.name} response did not match the expected shape: {e}",
            )

        if quote is None:
            return self._error(
                currency_from, currency_to,
                f"{self.name} returned no usable rate for {currency_from}->{currency_to}",
            )
        return quote

    # ------------------------------------------------------------------ #
    #  Subclass hooks
    # ------------------------------------------------------------------ #

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        """Return {method, url, headers, params, json} for this quote."""
        raise NotImplementedError

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        """Turn the decoded payload into a RawQuote, or None if unusable."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def first(data: Any, *paths: str, default=None):
        """
        Read the first present value among several dotted paths.

        Partner APIs rename fields between versions far more often than they
        change meaning, so each subclass lists the spellings it has seen rather
        than betting everything on one. A miss returns `default` instead of
        raising, which keeps one renamed field from taking out the provider.
        """
        for path in paths:
            cursor: Any = data
            for part in path.split("."):
                if isinstance(cursor, dict) and part in cursor:
                    cursor = cursor[part]
                else:
                    cursor = None
                    break
            if cursor is not None:
                return cursor
        return default
