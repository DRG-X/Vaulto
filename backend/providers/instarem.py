"""
InstaRemProvider — InstaReM (Nium) partner quote API.

India-focused, zero-fee model: InstaReM advertises no transfer fee and takes
its margin in the rate. The engine's `total_cost` is what makes that
comparable against a fee-charging provider at a better rate.

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://www.instarem.com/en-au (partner access via partnerships@instarem.com)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

#: InstaReM quotes same-day to next-day on the AU->IN corridor.
ETA_MIN_MINUTES = 60
ETA_MAX_MINUTES = 1440


class InstaRemProvider(PartnerAPIProvider):
    name = "InstaReM"

    QUOTE_URL = "https://api.instarem.com/v1/remittance/quote"

    meta = ProviderMeta(
        name="InstaReM",
        category=Category.FINTECH,
        integration=Integration.PARTNER_API,
        priority=2,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        credentials=("INSTAREM_API_KEY",),
        min_amount=Decimal('1'),
        max_amount=Decimal('500000'),
        limits_currency="AUD",
        website="https://www.instarem.com/en-au",
        notes="Zero-fee model — cost is entirely in the rate.",
    )

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "POST",
            "url": self.QUOTE_URL,
            "headers": {
                "X-Api-Key": self.credentials()["INSTAREM_API_KEY"],
                "Content-Type": "application/json",
            },
            "json": {
                "source_currency": currency_from.upper(),
                "destination_currency": currency_to.upper(),
                # String, not float — the amount must not be re-encoded
                # through a binary float on the way out.
                "source_amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        payload = self.first(data, "data", "quote", default=data)

        rate = D(
            self.first(payload, "fx_rate", "exchange_rate", "customer_rate"),
            default=None,
        )
        if not rate or rate <= ZERO:
            return None

        fee = D(self.first(payload, "total_fee", "transfer_fee", "fee"), default=ZERO)

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=fee or ZERO,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(
                self.first(payload, "destination_amount", "receive_amount"),
                default=None,
            ),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
        )
