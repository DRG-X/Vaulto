"""
providers/base.py — the contract every provider implements.

Providers return a `RawQuote` (their own terms, exact Decimals). The engine
re-bases and ranks. Providers do no comparison maths themselves — that is what
let three different rounding conventions drift apart in the first place.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

import httpx

from money import D
from providers.meta import Category, Integration, ProviderMeta
from providers.quote import RawQuote
from schemas import ProviderQuote


def decode_json_exact(response: httpx.Response) -> Any:
    """
    Parse a JSON response WITHOUT letting floats touch the numbers.

    This is the single highest-leverage precision fix in the codebase. By
    default `response.json()` turns `83.4210` on the wire into a binary float,
    and that value is already wrong before we do any arithmetic with it.
    Handing `parse_float=Decimal` to the decoder keeps the provider's exact
    digits as sent.

    It has to happen at DECODE time. Once the JSON library has produced a
    float the original digits are gone, and no amount of care downstream
    brings them back.
    """
    return json.loads(response.text, parse_float=Decimal, parse_int=Decimal)


class BaseProvider(ABC):
    name: str = "unknown"

    #: Static facts about this provider — corridors, credentials, category.
    #: The registry reads it to decide whether to call the provider at all,
    #: so a provider that cannot serve a corridor is never asked rather than
    #: being asked and reported as having failed.
    meta: ProviderMeta = ProviderMeta(
        name="unknown",
        category=Category.FINTECH,
        integration=Integration.PUBLIC_API,
    )

    @abstractmethod
    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        """
        Return this provider's quote in its own terms.

        `amount` is what the user asked to send. Providers should quote it as
        they natively would and declare their `fee_model`; re-basing onto a
        comparable footing is the engine's job, not theirs.

        Implementations should return a RawQuote carrying an `error` rather
        than raising, so one provider's outage cannot end the comparison.
        """
        ...

    async def fetch_quote(
        self, amount, currency_from: str, currency_to: str
    ) -> ProviderQuote:
        """
        Normalized single-provider quote.

        Kept so a provider can still be exercised on its own (scripts, the
        per-provider page, ad-hoc testing). Note that markup fields are absent
        here unless this provider publishes its own mid-market rate — markup
        needs a reference, and one provider in isolation has no yardstick.
        """
        from engine.normalize import normalize_quote  # local: avoids a cycle

        requested = D(amount)
        raw = await self.fetch_raw_quote(requested, currency_from, currency_to)
        return normalize_quote(raw, requested, raw.mid_market_rate)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _error(
        self, currency_from: str, currency_to: str, message: str
    ) -> RawQuote:
        return RawQuote(
            provider=self.name,
            currency_from=currency_from,
            currency_to=currency_to,
            error=message,
        )
