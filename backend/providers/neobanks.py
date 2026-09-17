"""
Limited-API providers — Niyo Global and SingX.

Both publish a consumer product with an API that is real but not openly
documented ("Limited" in the provider sheet), so both take their endpoint from
the environment and are skipped cleanly until one is configured.

Niyo matters for audience rather than price: it is heavily used by Indian
students, which makes it worth showing even when it does not win. SingX is the
opposite — good rates, low brand recognition in Australia, and a A$200 floor.

⚠️  Response shapes UNVERIFIED — see providers/partner_base.py.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

DAY = 1440


class _LimitedAPIProvider(PartnerAPIProvider):
    """Shared parsing for the two limited-API consumer products."""

    ETA_MIN_MINUTES = DAY
    ETA_MAX_MINUTES = 2 * DAY

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        key_name = self.meta.credentials[0]
        return {
            "method": "GET",
            "url": self.endpoint(),
            "headers": {"X-Api-Key": self.credentials()[key_name]},
            "params": {
                "sourceCurrency": currency_from.upper(),
                "targetCurrency": currency_to.upper(),
                "sourceAmount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        payload = self.first(data, "data", "quote", default=data)

        rate = D(
            self.first(payload, "rate", "fxRate", "exchangeRate", "customerRate"),
            default=None,
        )
        if not rate or rate <= ZERO:
            return None

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=D(self.first(payload, "fee", "totalFee", "transferFee"), default=ZERO) or ZERO,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(
                self.first(payload, "targetAmount", "receiveAmount"), default=None
            ),
            eta_min_minutes=self.ETA_MIN_MINUTES,
            eta_max_minutes=self.ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
        )


class NiyoGlobalProvider(_LimitedAPIProvider):
    name = "Niyo Global"

    DEFAULT_URL = ""                      # no published API documentation
    URL_ENV = "NIYO_API_URL"

    meta = ProviderMeta(
        name="Niyo Global",
        category=Category.NEOBANK,
        integration=Integration.PARTIAL_API,
        priority=3,
        corridors=(("INR", "AUD"),),
        credentials=("NIYO_API_KEY", "NIYO_API_URL"),
        min_amount=Decimal("1000"),
        max_amount=None,          # LRS is an annual allowance, not a per-transfer cap
        limits_currency="INR",
        website="https://www.niyomoney.com",
        notes="Popular with Indian students; forex card plus transfers.",
    )


class SingXProvider(_LimitedAPIProvider):
    name = "SingX"

    DEFAULT_URL = "https://api.singx.co/v1/quote"
    URL_ENV = "SINGX_API_URL"

    meta = ProviderMeta(
        name="SingX",
        category=Category.FINTECH,
        integration=Integration.PARTIAL_API,
        priority=4,
        cannot_send_from=("INR",),
        credentials=("SINGX_API_KEY",),
        min_amount=Decimal("200"),
        max_amount=Decimal("500000"),
        limits_currency="AUD",
        website="https://www.singx.co",
        notes="Singapore-based; good rates, low brand awareness in Australia.",
    )
