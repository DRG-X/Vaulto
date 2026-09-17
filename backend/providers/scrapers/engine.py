"""
providers/scrapers/engine.py — one provider class, driven by SiteConfig.

Nine scrape-only providers that differ only in a URL, a column name and a
direction do not need nine classes. They need one class and nine rows of data,
so that fixing a broken selector is a data edit rather than a code change.

⚠️  NONE OF THESE SELECTORS HAVE BEEN VERIFIED against a live page. Every
    provider host was blocked by this session's egress policy. Run
    `python -m scripts.verify_providers` from an unblocked network to see
    which pages still parse and correct `sites.py` accordingly.

A scraper that cannot find a rate returns an error quote. It never guesses,
never falls back to a cached constant, and never returns a number it is not
confident in — a wrong bank rate would rank a bank as the best deal, which is
the exact opposite of what these providers are here to demonstrate.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import httpx

from money import ONE, ZERO, quantize_rate
from providers.base import BaseProvider
from providers.meta import Integration, ProviderMeta
from providers.quote import FeeModel, RawQuote
from providers.scrapers.extract import extract_rate
from providers.scrapers.sites import SiteConfig

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9,en-IN;q=0.8",
}

TIMEOUT = 20


class ScrapeProvider(BaseProvider):
    """A provider whose rate is read off a public page."""

    def __init__(self, config: SiteConfig):
        self.config = config
        self.name = config.name
        self.meta = ProviderMeta(
            name=config.name,
            category=config.category,
            integration=Integration.SCRAPE,
            priority=config.priority,
            corridors=((config.send_currency, config.receive_currency),),
            benchmark_only=config.benchmark_only,
            avoid=config.avoid,
            needs_browser=config.requires_js,
            min_amount=config.min_amount,
            max_amount=config.max_amount,
            limits_currency=config.send_currency,
            website=config.url,
            notes=config.notes,
        )

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        cfg = self.config

        # The registry normally prevents this, but a provider called directly
        # must not silently answer for a corridor its page does not cover.
        if not self.meta.supports(currency_from, currency_to):
            return self._error(
                currency_from, currency_to,
                f"{self.name} publishes rates for "
                f"{cfg.send_currency}->{cfg.receive_currency} only",
            )

        try:
            html = await self._fetch_page(cfg.url)
        except Exception as e:
            return self._error(currency_from, currency_to, f"{self.name} page unreachable: {e}")

        published = extract_rate(
            html,
            # Always the RECEIVE currency: even an inverted rate card is
            # looked up by the currency being bought ("Australian Dollar"),
            # and the inversion happens afterwards in `_orient`.
            currency_code=cfg.receive_currency,
            currency_names=cfg.currency_names,
            column_hints=cfg.column_hints,
        )

        if published is None:
            if cfg.requires_js:
                # Distinct message on purpose: "needs a browser" and "the
                # selector broke" are different jobs, and telling a developer
                # to go fix a selector on a page that never had one in its
                # HTML wastes an afternoon.
                return self._error(
                    currency_from, currency_to,
                    f"{self.name}: rate is behind a JavaScript calculator at "
                    f"{cfg.url} and is not in the served HTML. Either find the "
                    f"JSON endpoint the calculator calls (as the Western Union "
                    f"provider does) and write a small API provider for it, or "
                    f"render the page with Playwright.",
                )
            return self._error(
                currency_from, currency_to,
                f"{self.name}: no {cfg.receive_currency} rate found on {cfg.url} "
                f"— the page layout has probably changed",
            )

        rate = self._orient(published)
        if rate is None:
            return self._error(
                currency_from, currency_to,
                f"{self.name}: published value {published} is not a usable rate",
            )

        logger.info(
            "[%s] scraped %s -> rate %s (published %s, inverted=%s)",
            self.name, cfg.url, rate, published, cfg.quotes_target_in_source,
        )

        return RawQuote(
            provider=self.name,
            currency_from=currency_from.upper(),
            currency_to=currency_to.upper(),
            principal=amount,
            fee=cfg.fee,
            # Banks debit the fee on top of the principal they convert.
            fee_model=FeeModel.ADDED,
            exchange_rate=rate,
            # The page gives a rate, never a receive amount — let the engine
            # derive it so the arithmetic is ours and auditable.
            receive_amount=None,
            eta_min_minutes=cfg.eta_min,
            eta_max_minutes=cfg.eta_max,
            eta_is_business_days=cfg.eta_business_days,
            pay_in_method="BANK",
            pay_out_method="BANK_DEPOSIT",
            service_name=cfg.fee_note or None,
            # Marks the quote as read off a page with an indicative fee, so a
            # client can present it with the right confidence.
            rate_type="scraped",
        )

    def _orient(self, published: Decimal) -> Optional[Decimal]:
        """
        Turn the page's published number into receive-per-send.

        Indian rate cards quote the send currency PER UNIT of the receive
        currency ("AUD 57.50" = one Australian dollar costs 57.50 rupees).
        Our rate has to be the other way round, so those get inverted. Getting
        this backwards on an INR->AUD quote inflates the result by roughly
        3,300x, which is why it is a single, explicit step rather than being
        folded into the extractor.
        """
        if not self.config.quotes_target_in_source:
            return published

        if published <= ZERO:
            return None
        try:
            return quantize_rate(ONE / published)
        except (InvalidOperation, ZeroDivisionError):
            return None

    async def _fetch_page(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers=BROWSER_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text


def build_scrape_providers(configs) -> List[ScrapeProvider]:
    return [ScrapeProvider(cfg) for cfg in configs]
