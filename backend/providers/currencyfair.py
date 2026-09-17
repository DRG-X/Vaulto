"""
CurrencyFairProvider — CurrencyFair marketplace rates.

CurrencyFair is peer-to-peer: you are matched against someone exchanging the
other way, and the pair meet in the middle. That has a consequence worth
stating, because it looks like a bug the first time you see it —

    **a CurrencyFair rate can legitimately BEAT mid-market.**

Every other provider in this comparison takes a margin, so `fx_markup_pct` is
positive for all of them. A matched P2P trade can settle better than the
interbank mid, producing a NEGATIVE markup. That is real, not a parsing error,
and the engine reports it as-is. The sanity band in `engine/sanity.py` is wide
enough (25%) to let a genuinely good P2P fill through while still catching an
inverted or mis-scaled rate.

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://help.currencyfair.com/api
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

#: CurrencyFair charges a flat fee per transfer on top of the matched rate.
TRANSFER_FEE = Decimal("3")

#: Marketplace matching plus settlement: 1-3 business days.
ETA_MIN_MINUTES = 1440
ETA_MAX_MINUTES = 3 * 1440


class CurrencyFairProvider(PartnerAPIProvider):
    name = "CurrencyFair"

    DEFAULT_URL = "https://currencyfair.com/api/v1/rates"
    URL_ENV = "CURRENCYFAIR_API_URL"

    meta = ProviderMeta(
        name="CurrencyFair",
        category=Category.P2P,
        integration=Integration.PARTNER_API,
        priority=3,
        # Receives rupees; cannot originate them (no RBI AD-II licence).
        cannot_send_from=("INR",),
        credentials=("CURRENCYFAIR_API_KEY",),
        min_amount=Decimal("8"),
        max_amount=Decimal("150000"),
        limits_currency="AUD",
        website="https://help.currencyfair.com/api",
        notes="Peer-to-peer marketplace; a matched rate can beat mid-market.",
    )

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "GET",
            "url": self.endpoint(),
            "headers": {"Authorization": f"Bearer {self.credentials()['CURRENCYFAIR_API_KEY']}"},
            "params": {
                "from": currency_from.upper(),
                "to": currency_to.upper(),
                "amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        payload = self.first(data, "data", "quote", default=data)

        rate = D(
            self.first(payload, "rate", "marketplaceRate", "bestRate", "exchangeRate"),
            default=None,
        )
        if not rate or rate <= ZERO:
            return None

        fee = D(self.first(payload, "fee", "transferFee", "totalFee"), default=None)

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=fee if fee is not None else TRANSFER_FEE,
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            receive_amount=D(self.first(payload, "receiveAmount", "toAmount"), default=None),
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            eta_is_business_days=True,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            service_name="Peer-to-peer marketplace match",
        )
