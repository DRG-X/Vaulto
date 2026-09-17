"""
RevolutProvider — Revolut exchange rates.

Revolut's headline promise is the mid-market rate, with two caveats that
matter enough to model rather than gloss over:

  * **Weekend markup.** Revolut applies a surcharge (typically ~1%) outside
    FX market hours. A Saturday quote is genuinely worse than a Tuesday one,
    and showing the weekday rate on a Saturday would misprice it. If the API
    reports the surcharge we use it; if it does not, `WEEKEND_MARKUP_PCT`
    is applied and the quote is flagged so the UI can say why.
  * **Plan allowances.** Free plans are fee-free only up to a monthly limit,
    after which a percentage fee applies. We cannot see a user's remaining
    allowance, so the fee is reported as zero and the caveat is carried in
    `service_name` rather than silently assumed away.

⚠️  Response shape UNVERIFIED — see providers/partner_base.py.
Docs: https://developer.revolut.com
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from money import D, ZERO, HUNDRED
from providers.meta import Category, Integration, ProviderMeta
from providers.partner_base import PartnerAPIProvider
from providers.quote import FeeModel, RawQuote

#: Applied when the API does not report its own weekend surcharge.
WEEKEND_MARKUP_PCT = Decimal("1.0")

ETA_MIN_MINUTES = 0
ETA_MAX_MINUTES = 120


def is_fx_weekend(now: Optional[datetime] = None) -> bool:
    """
    True when FX markets are closed and Revolut's surcharge applies.

    Markets close Friday ~21:00 UTC and reopen Sunday ~21:00 UTC, so the
    window is not simply "Saturday and Sunday" in any single timezone.
    """
    moment = now or datetime.now(timezone.utc)
    weekday = moment.weekday()          # Monday = 0
    if weekday == 5:                    # Saturday
        return True
    if weekday == 4 and moment.hour >= 21:      # Friday evening
        return True
    if weekday == 6 and moment.hour < 21:       # Sunday before reopen
        return True
    return False


class RevolutProvider(PartnerAPIProvider):
    name = "Revolut"

    RATE_URL = "https://b2b.revolut.com/api/1.0/rate"

    meta = ProviderMeta(
        name="Revolut",
        category=Category.NEOBANK,
        integration=Integration.PARTIAL_API,
        priority=2,
        credentials=("REVOLUT_API_KEY",),
        website="https://developer.revolut.com",
        notes="Weekend surcharge applies; free plans have monthly FX limits.",
    )

    def _build_request(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> Dict[str, Any]:
        return {
            "method": "GET",
            "url": self.RATE_URL,
            "headers": {"Authorization": f"Bearer {self.credentials()['REVOLUT_API_KEY']}"},
            "params": {
                "from": currency_from.upper(),
                "to": currency_to.upper(),
                "amount": str(amount),
            },
        }

    def _parse(
        self, data: Any, amount: Decimal, currency_from: str, currency_to: str
    ) -> Optional[RawQuote]:
        rate = D(self.first(data, "rate", "exchange_rate"), default=None)
        if not rate or rate <= ZERO:
            return None

        fee = D(self.first(data, "fee.amount", "fee"), default=ZERO) or ZERO

        # Revolut's weekday rate tracks mid-market closely, but we do NOT
        # publish it as the reference. Revolut is a competitor in the same
        # comparison, and a provider supplying the yardstick its own markup is
        # measured against scores itself a flattering 0% — the exact
        # self-serving reference that engine/normalize.py rules out. XE (a
        # data vendor with no stake in the result) is the reference; Wise is
        # the fallback.
        weekend = is_fx_weekend()
        surcharge_reported = self.first(data, "markup", "weekend_markup") is not None

        effective_rate = rate
        note = "Standard plan"

        if weekend and not surcharge_reported:
            # Worse rate for the customer: reduce what they receive.
            effective_rate = rate * (HUNDRED - WEEKEND_MARKUP_PCT) / HUNDRED
            note = f"Weekend surcharge ~{WEEKEND_MARKUP_PCT}% applied"
        elif weekend:
            note = "Weekend surcharge included by Revolut"

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=fee,
            fee_model=FeeModel.ADDED,
            exchange_rate=effective_rate,
            receive_amount=None,        # let the engine derive it from our rate
            eta_min_minutes=ETA_MIN_MINUTES,
            eta_max_minutes=ETA_MAX_MINUTES,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            service_name=note,
        )
