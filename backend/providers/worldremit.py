"""
WorldRemitProvider — WorldRemit partner quotes.

Worth having for one reason the rate alone does not show: WorldRemit pays out
to **UPI** on the India corridor. For a student sending money to a parent's
phone rather than a bank account that is a genuine differentiator, so the
payout rail is reported rather than flattened to "bank deposit".

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://www.worldremit.com/en/business (partnerships@worldremit.com)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

ETA_MIN_MINUTES = 15
ETA_MAX_MINUTES = 8 * 60

#: WorldRemit's payout rails, preferred rail first. UPI and mobile wallet are
#: the fast ones on the India corridor.
PAYOUT_ALIASES = {
    "BANK_DEPOSIT": "BANK_DEPOSIT",
    "BANKDEPOSIT": "BANK_DEPOSIT",
    "UPI": "UPI",
    "MOBILE": "MOBILE_WALLET",
    "MOBILE_MONEY": "MOBILE_WALLET",
    "CASH": "CASH_PICKUP",
    "CASH_PICKUP": "CASH_PICKUP",
}


class WorldRemitProvider(PartnerAPIProvider):
    name = "WorldRemit"

    DEFAULT_URL = "https://api.worldremit.com/v1/quotes"
    URL_ENV = "WORLDREMIT_API_URL"

    meta = ProviderMeta(
        name="WorldRemit",
        category=Category.FINTECH,
        integration=Integration.PARTNER_API,
        priority=3,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        credentials=("WORLDREMIT_API_KEY",),
        min_amount=Decimal("1"),
        max_amount=Decimal("9000"),
        limits_currency="AUD",
        website="https://www.worldremit.com/en/business",
        notes="Supports UPI payout to India — a real differentiator, not just a rate.",
    )

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "GET",
            "url": self.endpoint(),
            "headers": {"Authorization": f"Bearer {self.credentials()['WORLDREMIT_API_KEY']}"},
            "params": {
                "sendCurrency": currency_from.upper(),
                "receiveCurrency": currency_to.upper(),
                "sendAmount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        payload = self.first(data, "quote", "data", default=data)

        rate = D(self.first(payload, "exchangeRate", "rate"), default=None)
        if not rate or rate <= ZERO:
            return None

        raw_payout = str(self.first(payload, "payOutMethod", "deliveryMethod") or "").upper()
        payout = PAYOUT_ALIASES.get(raw_payout.replace(" ", "_"), raw_payout or None)

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=D(self.first(payload, "fee", "totalFee", "transferFee"), default=ZERO) or ZERO,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(self.first(payload, "receiveAmount"), default=None),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            pay_in_method="BANK",
            pay_out_method=payout or "BANK_DEPOSIT",
        )
