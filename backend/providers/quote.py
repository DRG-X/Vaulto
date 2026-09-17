"""
providers/quote.py — the raw, un-normalized quote a provider returns.

Providers speak in their own terms. The single most important difference
between them, and the one that made this engine's comparisons wrong, is WHERE
THE FEE SITS relative to the amount being converted:

    Wise    you ask to send 1000, Wise takes its fee OUT of the 1000 and
            converts the remainder. You pay 1000. `receive = (1000-fee) * rate`

    Remitly you ask to send 1000, Remitly converts the full 1000 and charges
    & WU    the fee ON TOP. You pay 1000+fee. `receive = 1000 * rate`

Ranking those two `receive` figures against each other compares a sender who
spent 1000 with a sender who spent 1000+fee. The fee-on-top providers come out
systematically ahead by roughly `fee * rate` — about 330 INR on a 1000 USD
transfer with a $4 fee. Small enough to look like a rounding glitch, large
enough to hand the win to the wrong provider.

So providers return a `RawQuote` stating their fee model explicitly.

A fee-on-top provider uses that knowledge on its own side: it re-quotes at
`budget - fee` so its TIERED fee schedule produces the real number rather than
us assuming the first tier holds. `engine/normalize.py` then puts every quote
on the one basis, and the declared model rides along into the response as
provenance — it is what explains two providers reporting different receive
amounts from the same rate and fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class FeeModel(str, Enum):
    """Where the provider's fee sits relative to the converted principal."""

    #: Fee is taken out of the amount the sender hands over.
    #: total_paid = principal + fee is FALSE; total_paid = amount_requested.
    DEDUCTED = "deducted"

    #: Fee is charged on top of the converted principal.
    #: total_paid = principal + fee.
    ADDED = "added"


@dataclass
class RawQuote:
    """
    One provider's answer, in that provider's own terms, with exact Decimals.

    `principal` is the amount the provider actually converts at `exchange_rate`
    — NOT necessarily the amount the user asked to send. `fee` is in the send
    currency. `receive_amount` is the provider's own published figure when it
    gives one; we keep it so we can cross-check our arithmetic against theirs
    instead of silently replacing it.
    """

    provider: str
    currency_from: str
    currency_to: str

    principal: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    fee_model: FeeModel = FeeModel.DEDUCTED
    exchange_rate: Decimal = Decimal("0")

    #: The provider's own receive figure, if published. None means "we must
    #: compute it ourselves".
    receive_amount: Optional[Decimal] = None

    # ── delivery timing (minutes; see delivery.py) ──
    eta_min_minutes: Optional[int] = None
    eta_max_minutes: Optional[int] = None
    eta_is_business_days: bool = False

    # ── how the money moves ──
    pay_in_method: Optional[str] = None
    pay_out_method: Optional[str] = None
    service_name: Optional[str] = None

    # ── rate provenance ──
    #: True when the quoted rate is a limited-time or first-transfer promo.
    #: Promos are real money to the user but are not repeatable, so the engine
    #: lets callers exclude them rather than letting them distort a comparison.
    is_promotional: bool = False
    rate_type: str = "base"

    #: Mid-market rate for the corridor, when the provider publishes one.
    #: Wise's comparison endpoint does, and XE's currency-data API does.
    mid_market_rate: Optional[Decimal] = None

    #: True when this quote exists ONLY to supply `mid_market_rate`. The
    #: engine harvests the reference and does not rank the quote — see
    #: `ProviderMeta.rate_reference_only`.
    reference_only: bool = False

    #: Every delivery option the provider offered, for transparency and for
    #: filter modes that want a non-default option (e.g. fastest).
    options: list = field(default_factory=list)

    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when this quote carries usable numbers."""
        return (
            self.error is None
            and self.exchange_rate > 0
            and self.principal > 0
        )
