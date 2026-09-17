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
from typing import Tuple


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

    website: str = ""
    notes: str = ""

    def supports(self, currency_from: str, currency_to: str) -> bool:
        """True when this provider operates on the given corridor."""
        send, receive = currency_from.upper(), currency_to.upper()
        for rule_send, rule_receive in self.corridors:
            if rule_send not in (ANY, send):
                continue
            if rule_receive not in (ANY, receive):
                continue
            return True
        return False

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
