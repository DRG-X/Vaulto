"""Scrape-only providers, built from the declarative table in `sites.py`."""

from providers.scrapers.engine import ScrapeProvider, build_scrape_providers
from providers.scrapers.sites import ALL_SITES, SiteConfig

#: Every scrape-backed provider, in provider-sheet priority order.
SCRAPE_PROVIDERS = build_scrape_providers(
    sorted(ALL_SITES, key=lambda c: (c.priority, c.name))
)

__all__ = ["SCRAPE_PROVIDERS", "ScrapeProvider", "SiteConfig", "ALL_SITES", "build_scrape_providers"]
