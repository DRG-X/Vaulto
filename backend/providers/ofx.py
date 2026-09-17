"""
OFXProvider — OFX partner rates API.

Fee model: OFX charges NO transfer fee above A$200 and builds its margin into
the rate. Below that threshold a fixed fee applies. Both are declared here
rather than assumed, because a provider reporting fee 0 with an unstated
margin is exactly the "free transfer" illusion the engine exists to expose —
`total_cost` will show OFX's real price once a mid-market reference is present.

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://www.ofx.com/en-au/business/api
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

#: Transfers at or above this amount are fee-free.
FEE_FREE_THRESHOLD = Decimal("200")
SMALL_TRANSFER_FEE = Decimal("15")

#: OFX settles bank-to-bank; 1-2 business days on major corridors.
ETA_MIN_MINUTES = 1440
ETA_MAX_MINUTES = 2880


class OFXProvider(PartnerAPIProvider):
    name = "OFX"

    RATE_URL = "https://api.ofx.com/rate"

    meta = ProviderMeta(
        name="OFX",
        category=Category.FINTECH,
        integration=Integration.PARTNER_API,
        priority=2,
        credentials=("OFX_API_KEY",),
        website="https://www.ofx.com/en-au/business/api",
        notes="No transfer fee above A$200; margin is in the rate.",
    )

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "GET",
            "url": self.RATE_URL,
            "headers": {"Authorization": f"Bearer {self.credentials()['OFX_API_KEY']}"},
            "params": {
                "sellCurrency": currency_from.upper(),
                "buyCurrency": currency_to.upper(),
                "amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        rate = D(self.first(data, "CustomerRate", "customerRate", "rate", "Rate"), default=None)
        if not rate or rate <= ZERO:
            return None

        # OFX also publishes the interbank rate it priced against, which is a
        # usable mid-market reference in its own right.
        mid = D(self.first(data, "InterbankRate", "interbankRate", "midRate"), default=None)

        fee = ZERO if amount >= FEE_FREE_THRESHOLD else SMALL_TRANSFER_FEE

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=fee,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(self.first(data, "BuyAmount", "buyAmount"), default=None),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            mid_market_rate=mid if mid and mid > ZERO else None,
        )
