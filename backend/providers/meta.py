"""
providers/meta.py — what each provider IS, separate from how it quotes.

Adding fifteen providers surfaced three facts the flat `ALL_PROVIDERS` list
could not express, each of which produces wrong output if ignored:

1. **Providers serve specific corridors.** State Bank of India sends INR out
   of India. Asking it about USD->INR is not a failure worth reporting, it is
   a question that should never have been asked. Without corridor metadata
   every India-side provider would appear in `failed_providers` on every
   Australian corridor, making a working system look broken.

2. **Most partner APIs need credentials you have to apply for.** OFX,
   InstaReM, Airwallex and Revolut all gate their pricing behind an approved
   partner key. A provider with no key configured is not down — it is not set
   up yet, and saying so is actionable where "failed" is not.

3. **Not every provider is for showing.** The build tracker marks HOP Remit
   "Competitor — benchmark only, don't display". It has to be fetchable for
   rate benchmarking and invisible in the comparison users see.

`avoid` carries the other half of the product thesis: the big banks are in the
list precisely BECAUSE they are terrible. Flagging them lets the UI show the
gap rather than quietly ranking them last.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import Optional, Tuple


class Category(str, Enum):
    FINTECH = "fintech"
    BANK = "bank"
    NEOBANK = "neobank"
    LEGACY = "legacy"
    BROKER = "broker"
    P2P = "p2p"


class Integration(str, Enum):
    #: Public endpoint, no credentials.
    PUBLIC_API = "public_api"
    #: Requires an approved partner key.
    PARTNER_API = "partner_api"
    #: Officially limited/partial API.
    PARTIAL_API = "partial_api"
    #: No API — the rate is read off a public page.
    SCRAPE = "scrape"


#: Wildcard for "any currency" in a corridor rule.
ANY = "*"

#: A provider that works on essentially every corridor it has a mapping for.
ANY_CORRIDOR: Tuple[Tuple[str, str], ...] = ((ANY, ANY),)


@dataclass(frozen=True)
class ProviderMeta:
    """Static facts about a provider. No network, no quoting."""

    name: str
    category: Category
    integration: Integration

    #: 1 = Critical, 2 = High, 3 = Medium, 4 = Low. From the provider sheet.
    priority: int = 3

    #: Corridor rules as (send, receive) pairs; "*" matches anything.
    #: ("AUD", ANY) means "sends Australian dollars anywhere".
    corridors: Tuple[Tuple[str, str], ...] = ANY_CORRIDOR

    #: Currencies this provider cannot SEND FROM, whatever `corridors` allows.
    #:
    #: Moving money OUT of India requires an RBI AD-II licence under the
    #: Liberalised Remittance Scheme. The global fintechs and brokers here
    #: receive rupees; they do not originate them. Wise is the exception —
    #: it runs an Indian entity, which is what the provider sheet lists
    #: separately as "Wise India".
    #:
    #: Without this, every AU-side provider would be offered on the INR->AUD
    #: corridor, fail confusingly, and — for the credential-gated ones —
    #: quietly burn a partner API call per comparison on a transfer they
    #: would refuse.
    cannot_send_from: Tuple[str, ...] = ()

    #: Environment variables that must ALL be set for this provider to run.
    credentials: Tuple[str, ...] = ()

    #: Fetched for internal rate benchmarking, never shown to users.
    benchmark_only: bool = False

    #: Contributes a mid-market REFERENCE rate but no rankable quote.
    #:
    #: Some endpoints publish the mid-market rate without the retail pricing
    #: built on top of it — XE's currency-data API is the clearest case. That
    #: rate is valuable (it is the yardstick every markup is measured against)
    #: but it is NOT what the provider would actually sell you. Ranking it as
    #: a quote would show a flat 0% markup and win every comparison on a price
    #: nobody can buy.
    rate_reference_only: bool = False

    #: Known-bad pricing kept in the comparison to show the gap.
    avoid: bool = False

    #: True when the rate only exists after JavaScript runs, so no amount of
    #: HTTP fetching will find it.
    #:
    #: These are registered so corridor coverage is honest, but they are NOT
    #: called: doing so would spend a 20-second timeout on every comparison
    #: and park two permanent entries in `failed_providers` — precisely the
    #: "healthy system looks broken" failure this metadata exists to prevent.
    #: They are reported as unavailable, with what they actually need.
    needs_browser: bool = False

    # ── Transfer limits ──────────────────────────────────────────────────
    # Providers will not move any amount you like. TorFX starts at A$2,000;
    # WorldRemit stops at A$9,000. Quoting either outside its band is not a
    # near-miss, it is an offer the provider would refuse — and it would
    # usually WIN, because brokers with high minimums have the best rates.
    #
    # Limits are denominated in a specific currency, so they are only applied
    # when the send currency matches `limits_currency`. Comparing A$2,000
    # against a rupee amount needs an exchange rate we do not have at
    # selection time, and a wrong guess there would wrongly exclude a
    # provider. Not checking is the safe failure.
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    limits_currency: Optional[str] = None

    website: str = ""
    notes: str = ""

    def supports(self, currency_from: str, currency_to: str) -> bool:
        """True when this provider operates on the given corridor."""
        send, receive = currency_from.upper(), currency_to.upper()

        if send in {c.upper() for c in self.cannot_send_from}:
            return False

        for rule_send, rule_receive in self.corridors:
            if rule_send not in (ANY, send):
                continue
            if rule_receive not in (ANY, receive):
                continue
            return True
        return False

    def accepts_amount(
        self, amount: Decimal, currency_from: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Whether this provider will move `amount`, and why not if it will not.

        Returns (True, None) when the limits do not apply — either none are
        declared, or they are denominated in a currency other than the one
        being sent. Silence beats a guess: excluding a provider on a converted
        limit we cannot compute would hide a real option.
        """
        if self.limits_currency and currency_from.upper() != self.limits_currency.upper():
            return (True, None)

        unit = self.limits_currency or currency_from.upper()

        if self.min_amount is not None and amount < self.min_amount:
            return (False, f"Minimum transfer is {_plain(self.min_amount)} {unit}")

        if self.max_amount is not None and amount > self.max_amount:
            return (False, f"Maximum transfer is {_plain(self.max_amount)} {unit}")

        return (True, None)

    @property
    def missing_credentials(self) -> Tuple[str, ...]:
        """Credential env vars that are required but absent or blank."""
        return tuple(
            name for name in self.credentials
            if not (os.getenv(name) or "").strip()
        )

    @property
    def is_configured(self) -> bool:
        """
        True when this provider can actually be called.

        Read at call time rather than import time so a key added to the
        environment takes effect without a code change, and so tests can set
        one with monkeypatch.
        """
        return not self.missing_credentials


def _plain(value: Decimal) -> str:
    """Render a limit without scientific notation or trailing zeros."""
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")
