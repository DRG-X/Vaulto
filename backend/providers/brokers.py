"""
Broker providers — TorFX and Moneycorp.

Both are dealer-desk brokers rather than self-serve fintechs, and that shapes
the integration in two ways:

**They publish no API URL.** Both list "contact us" rather than documentation,
so there is no endpoint to hard-code. Inventing a plausible-looking one would
produce 404s that read as an outage rather than as "you have not been onboarded
yet", so the URL comes from an environment variable and the provider says so
plainly when it is unset.

**They have high minimums** — A$2,000 for TorFX, A$1,000 for Moneycorp. This is
not a detail: brokers offer their best rates precisely because they will not
take small transfers, so without the minimum enforced they would win the
comparison for a student sending A$500 with a quote that provider would refuse.
The registry excludes them below their floor before any call is made.

Their pricing is a negotiated spread with no visible fee, which is exactly the
shape `total_cost` exists to expose: zero fee, all margin in the rate.

⚠️  Response shapes UNVERIFIED — see providers/partner_base.py.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

#: Broker settlement runs 1-2 business days on major corridors.
ETA_MIN_MINUTES = 1440
ETA_MAX_MINUTES = 2880


class _BrokerProvider(PartnerAPIProvider):
    """Shared parsing for negotiated-rate dealer desks."""

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        key_name = self.meta.credentials[0]
        return {
            "method": "GET",
            "url": self.endpoint(),
            "headers": {"Authorization": f"Bearer {self.credentials()[key_name]}"},
            "params": {
                "sellCurrency": currency_from.upper(),
                "buyCurrency": currency_to.upper(),
                "amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        # "rate" is deliberately NOT a container path here: it is also a LEAF
        # field name below, and a flat {"rate": 54.9} response would make
        # `payload` the number itself, leaving every lookup empty and the
        # provider reporting "no usable rate" on a perfectly good answer.
        payload = self.first(data, "quote", "data", default=data)

        rate = D(
            self.first(payload, "customerRate", "clientRate", "rate", "dealRate"),
            default=None,
        )
        if not rate or rate <= ZERO:
            return None

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            # No visible fee — brokers price entirely in the spread, which
            # `total_cost` surfaces once a mid-market reference is present.
            fee=D(self.first(payload, "fee", "commission"), default=ZERO) or ZERO,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(self.first(payload, "buyAmount", "receiveAmount"), default=None),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            service_name="Negotiated broker rate",
        )


class TorFXProvider(_BrokerProvider):
    name = "TorFX"

    DEFAULT_URL = ""                      # published as "contact directly"
    URL_ENV = "TORFX_API_URL"

    meta = ProviderMeta(
        name="TorFX",
        category=Category.BROKER,
        integration=Integration.PARTNER_API,
        priority=3,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        credentials=("TORFX_API_KEY", "TORFX_API_URL"),
        min_amount=Decimal("2000"),
        max_amount=None,
        limits_currency="AUD",
        website="https://www.torfx.com",
        notes="Personal broker model; A$2,000 minimum. Endpoint issued on onboarding.",
    )


class MoneycorpProvider(_BrokerProvider):
    name = "Moneycorp"

    DEFAULT_URL = "https://api.moneycorp.com/v1/rates"
    URL_ENV = "MONEYCORP_API_URL"

    meta = ProviderMeta(
        name="Moneycorp",
        category=Category.BROKER,
        integration=Integration.PARTNER_API,
        priority=4,
        cannot_send_from=("INR",),
        credentials=("MONEYCORP_API_KEY",),
        min_amount=Decimal("1000"),
        max_amount=None,
        limits_currency="AUD",
        website="https://www.moneycorp.com/api",
        notes="Enterprise-focused; A$1,000 minimum. Included for high-value transfers.",
    )
