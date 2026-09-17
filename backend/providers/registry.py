"""
providers/registry.py — which providers to ask, for this particular request.

The old `ALL_PROVIDERS` list was asked everything on every request. With three
broad-corridor providers that was fine. With eighteen, most of them
corridor-specific or credential-gated, it produces noise that looks like
breakage: every India-side bank reported as "failed" on an Australian
corridor, every unapproved partner API reported as "failed" when it is simply
not set up yet.

So selection happens before any network call, and the reasons a provider was
left out are reported separately from the reasons one failed. Those are
different problems with different fixes — "not available here", "needs a key
you have to apply for", and "it broke" should never be the same message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from providers.base import BaseProvider

# ── API providers ───────────────────────────────────────────────────────────
from providers.wise import WiseProvider
from providers.remitly import RemitlyProvider
from providers.western_union import WesternUnionProvider
from providers.xe import XEProvider
from providers.ofx import OFXProvider
from providers.instarem import InstaRemProvider
from providers.airwallex import AirwallexProvider
from providers.revolut import RevolutProvider

# ── Scrape-only providers (rate pages, no API) ──────────────────────────────
from providers.scrapers import SCRAPE_PROVIDERS


#: Every provider Vaulto knows about, in provider-sheet priority order.
ALL_PROVIDERS: List[BaseProvider] = [
    # Priority 1 — Critical
    WiseProvider(),
    RemitlyProvider(),
    XEProvider(),
    # Priority 2 — High
    WesternUnionProvider(),
    OFXProvider(),
    InstaRemProvider(),
    AirwallexProvider(),
    RevolutProvider(),
    # Scrape-only: AU banks, India banks, India fintech, benchmark-only
    *SCRAPE_PROVIDERS,
]


@dataclass
class Selection:
    """Which providers to call, and why the others were left out."""

    active: List[BaseProvider] = field(default_factory=list)

    #: Provider name -> corridor it does not serve.
    out_of_corridor: Dict[str, str] = field(default_factory=dict)

    #: Provider name -> the env vars it still needs.
    needs_credentials: Dict[str, List[str]] = field(default_factory=dict)

    #: Fetched for benchmarking but never shown to users.
    benchmark: List[BaseProvider] = field(default_factory=list)

    @property
    def unavailable(self) -> Dict[str, str]:
        """A flat, user-facing explanation per skipped provider."""
        out: Dict[str, str] = {}
        for name, corridor in self.out_of_corridor.items():
            out[name] = f"Does not serve {corridor}"
        for name, missing in self.needs_credentials.items():
            out[name] = (
                "Not configured — set "
                + ", ".join(missing)
                + " to enable this provider"
            )
        return out


def select_providers(
    currency_from: str,
    currency_to: str,
    providers: Sequence[BaseProvider] | None = None,
    include_benchmark: bool = False,
) -> Selection:
    """
    Pick the providers worth calling for this corridor.

    A provider is skipped when it does not serve the corridor, or when a
    credential it needs is not configured. Benchmark-only providers are
    separated out: they are fetched (when asked for) so their rates can be
    tracked, but they never reach the comparison a user sees.
    """
    pool = list(providers if providers is not None else ALL_PROVIDERS)
    corridor = f"{currency_from.upper()}->{currency_to.upper()}"
    selection = Selection()

    for provider in pool:
        meta = provider.meta

        if not meta.supports(currency_from, currency_to):
            selection.out_of_corridor[provider.name] = corridor
            continue

        missing = meta.missing_credentials
        if missing:
            selection.needs_credentials[provider.name] = list(missing)
            continue

        if meta.benchmark_only:
            if include_benchmark:
                selection.benchmark.append(provider)
            continue

        selection.active.append(provider)

    return selection
