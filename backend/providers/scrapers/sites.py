"""
providers/scrapers/sites.py — one row per scrape-only provider.

Every value here is EDITABLE DATA, not logic. That is the point: none of these
selectors could be verified from this environment (all provider hosts are
blocked by egress policy), and bank rate pages change without notice anyway.
When one breaks, the fix is a value in this table, not a new parser.

Two things in here are easy to get wrong and expensive when you do:

**Rate direction.** Australian bank pages quote "1 AUD = 54.23 INR" — the
target currency priced per unit of source, which is the rate we want as-is.
Indian bank rate cards quote the opposite: "AUD 57.50" meaning one Australian
dollar costs 57.50 rupees. For an INR->AUD transfer that has to be INVERTED,
or the quote comes out roughly 3,300x too good and wins every comparison.
`quotes_target_in_source` controls this.

**Which column.** Banks publish several rates per currency. The cash/notes
rate is materially worse than the telegraphic-transfer rate used for wires,
and grabbing the wrong one misprices the provider. `column_hints` lists the
column headers we want, in priority order.

Fees are the OPTIMISTIC end of each published range. These providers are in
the comparison to show how much they cost, so any error should understate
that, never inflate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from providers.meta import Category

DAY = 1440


@dataclass(frozen=True)
class SiteConfig:
    """Everything needed to read one provider's published rate."""

    name: str
    url: str
    category: Category
    priority: int

    #: Corridor this page serves, as (send, receive).
    send_currency: str
    receive_currency: str

    #: Flat transfer fee, in the SEND currency. The low end of the published
    #: range — see module docstring.
    fee: Decimal
    fee_note: str = ""

    #: Delivery window in minutes, and whether the source quoted business days.
    eta_min: int = 2 * DAY
    eta_max: int = 5 * DAY
    eta_business_days: bool = True

    #: True when the page prices ONE UNIT OF THE RECEIVE CURRENCY in the send
    #: currency (Indian rate-card convention) and the rate must be inverted.
    quotes_target_in_source: bool = False

    #: Column headers to prefer, best first.
    column_hints: Tuple[str, ...] = ()

    #: Alternative spellings of the currency to match on, beyond its code.
    currency_names: Tuple[str, ...] = ()

    #: Known-bad pricing, kept in the comparison to show the gap.
    avoid: bool = False

    #: Fetched for benchmarking only; never shown to users.
    benchmark_only: bool = False

    #: Transfer band, in the SEND currency. None means no published limit.
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None

    #: True when the rate lives behind a JavaScript calculator rather than in
    #: server-rendered HTML. A plain GET returns the page shell with no rate
    #: in it, so these need either the JSON endpoint the calculator calls or a
    #: real browser (Playwright). They are registered so the corridor coverage
    #: is honest, and the verification script reports them distinctly instead
    #: of as a generic parse failure — "needs a browser" and "the selector
    #: broke" are different jobs.
    requires_js: bool = False

    notes: str = ""


#: Australian banks — send AUD. Pages quote foreign currency per 1 AUD.
AU_BANKS: Sequence[SiteConfig] = (
    SiteConfig(
        name="CommBank",
        min_amount=Decimal("1"),
        max_amount=None,
        url="https://www.commbank.com.au/personal/international/foreign-exchange-rates",
        category=Category.BANK,
        priority=1,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("22"),
        fee_note="A$22 international transfer fee",
        column_hints=("TT SELL", "TELEGRAPHIC", "SELL", "WE SELL"),
        currency_names=("INDIAN RUPEE",),
        avoid=True,
        notes="Worst rate of the big four — the gap Vaulto exists to show.",
    ),
    SiteConfig(
        name="ANZ",
        min_amount=Decimal("1"),
        max_amount=None,
        url="https://www.anz.com.au/personal/travel-international/foreign-exchange/",
        category=Category.BANK,
        priority=2,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("20"),
        fee_note="A$20-25 international transfer fee",
        column_hints=("TT SELL", "TELEGRAPHIC", "SELL"),
        currency_names=("INDIAN RUPEE",),
        avoid=True,
    ),
    SiteConfig(
        name="NAB",
        min_amount=Decimal("1"),
        max_amount=None,
        url="https://www.nab.com.au/personal/international-banking/foreign-exchange-rates",
        category=Category.BANK,
        priority=3,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("18"),
        fee_note="A$18-22 international transfer fee",
        column_hints=("TT SELL", "TELEGRAPHIC", "SELL"),
        currency_names=("INDIAN RUPEE",),
        avoid=True,
        notes="Big four; marginally better than CommBank, still far off fintech rates.",
    ),
    SiteConfig(
        name="Westpac",
        min_amount=Decimal("1"),
        max_amount=None,
        url="https://www.westpac.com.au/personal-banking/foreign-exchange/exchange-rates/",
        category=Category.BANK,
        priority=2,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("20"),
        fee_note="A$20-25 international transfer fee",
        column_hints=("TT SELL", "TELEGRAPHIC", "SELL"),
        currency_names=("INDIAN RUPEE",),
        avoid=True,
    ),
)


#: Indian banks — send INR. Rate cards quote INR per 1 unit of foreign
#: currency, so every one of these needs inverting.
IN_BANKS: Sequence[SiteConfig] = (
    SiteConfig(
        name="SBI",
        min_amount=Decimal("1000"),
        max_amount=None,
        url="https://www.sbi.co.in/web/interest-rates/forex-card-rates",
        category=Category.BANK,
        priority=1,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("500"),
        fee_note="₹500-2,000 plus GST on outward remittance",
        eta_min=3 * DAY,
        eta_max=5 * DAY,
        quotes_target_in_source=True,
        column_hints=("TT SELL", "TT SELLING", "SELL"),
        currency_names=("AUSTRALIAN DOLLAR", "AUD/INR"),
        avoid=True,
        notes="Most Indian parents default to SBI; worst rates on the corridor.",
    ),
    SiteConfig(
        name="HDFC Bank",
        min_amount=Decimal("1000"),
        max_amount=None,
        url="https://www.hdfcbank.com/personal/resources/rates",
        category=Category.BANK,
        priority=2,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("500"),
        fee_note="₹500-1,500 plus GST",
        eta_min=2 * DAY,
        eta_max=4 * DAY,
        quotes_target_in_source=True,
        column_hints=("TT SELL", "TT SELLING", "SELL"),
        currency_names=("AUSTRALIAN DOLLAR",),
        avoid=True,
    ),
    SiteConfig(
        name="ICICI Bank",
        min_amount=Decimal("1000"),
        max_amount=None,
        url="https://www.icicibank.com/personal-banking/forex/fx-rates",
        category=Category.BANK,
        priority=2,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("400"),
        fee_note="₹400-1,200 plus GST",
        eta_min=2 * DAY,
        eta_max=4 * DAY,
        quotes_target_in_source=True,
        column_hints=("TT SELL", "TT SELLING", "SELL"),
        currency_names=("AUSTRALIAN DOLLAR",),
        avoid=True,
    ),
    SiteConfig(
        name="Axis Forex",
        min_amount=Decimal("5000"),
        max_amount=None,
        url="https://www.axisbank.com/forex/forex-card/exchange-rate",
        category=Category.BANK,
        priority=3,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("300"),
        fee_note="₹300-800 plus GST",
        eta_min=2 * DAY,
        eta_max=3 * DAY,
        quotes_target_in_source=True,
        column_hints=("TT SELL", "TT SELLING", "SELL"),
        currency_names=("AUSTRALIAN DOLLAR",),
        avoid=True,
        notes="Axis Bank's forex arm; popular in metro cities.",
    ),
)


#: India-side fintech — send INR, far better rates than the banks above.
IN_FINTECH: Sequence[SiteConfig] = (
    SiteConfig(
        name="BookMyForex",
        min_amount=Decimal("1000"),
        max_amount=Decimal("1500000"),
        url="https://www.bookmyforex.com/forex-rates/",
        category=Category.FINTECH,
        priority=2,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("100"),
        fee_note="₹100-500 depending on amount",
        eta_min=1 * DAY,
        eta_max=2 * DAY,
        quotes_target_in_source=True,
        column_hints=("SELL", "RATE"),
        currency_names=("AUSTRALIAN DOLLAR",),
        notes="India's leading forex marketplace; the realistic India-side benchmark.",
    ),
    SiteConfig(
        name="ExTravelMoney",
        min_amount=Decimal("500"),
        max_amount=Decimal("1000000"),
        url="https://www.extravelmoney.com/forex-rates/",
        category=Category.FINTECH,
        priority=2,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("0"),
        fee_note="₹0-200 depending on partner",
        eta_min=1 * DAY,
        eta_max=2 * DAY,
        quotes_target_in_source=True,
        column_hints=("SELL", "RATE"),
        currency_names=("AUSTRALIAN DOLLAR",),
    ),
    SiteConfig(
        name="Thomas Cook India",
        min_amount=Decimal("5000"),
        max_amount=Decimal("1500000"),
        url="https://www.thomascook.in/foreign-exchange/forex-rates",
        category=Category.LEGACY,
        priority=3,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("200"),
        fee_note="₹200-500 plus GST",
        eta_min=2 * DAY,
        eta_max=3 * DAY,
        quotes_target_in_source=True,
        column_hints=("SELL", "RATE"),
        currency_names=("AUSTRALIAN DOLLAR",),
        notes="Legacy brand, heavily trusted by Indian parents aged 40+.",
    ),
)


#: Providers whose rate lives behind a JavaScript calculator. Registered so
#: corridor coverage is honest; see `SiteConfig.requires_js` for why a plain
#: fetch will not get a rate out of them.
JS_CALCULATORS: Sequence[SiteConfig] = (
    SiteConfig(
        name="MoneyGram",
        min_amount=Decimal("1"),
        max_amount=Decimal("10000"),
        url="https://www.moneygram.com/mgo/au/en/",
        category=Category.LEGACY,
        priority=3,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("5"),
        fee_note="A$5-20 depending on speed and payout method",
        eta_min=15,
        eta_max=3 * DAY,
        eta_business_days=False,
        column_hints=("RATE",),
        currency_names=("INDIAN RUPEE",),
        requires_js=True,
        notes="Still used by older demographics. Needs the calculator's JSON endpoint.",
    ),
    SiteConfig(
        name="Panda Remit",
        min_amount=Decimal("10"),
        max_amount=Decimal("50000"),
        url="https://www.pandaremit.com/en-AU",
        category=Category.FINTECH,
        priority=3,
        send_currency="AUD",
        receive_currency="INR",
        fee=Decimal("0"),
        fee_note="A$0-3 depending on amount",
        eta_min=60,
        eta_max=12 * 60,
        eta_business_days=False,
        column_hints=("RATE",),
        currency_names=("INDIAN RUPEE",),
        requires_js=True,
        notes="Growing fast with the Asian student community.",
    ),
)


#: Competitors we track but never display.
BENCHMARK: Sequence[SiteConfig] = (
    SiteConfig(
        name="HOP Remit",
        min_amount=Decimal("1000"),
        max_amount=None,
        url="https://www.moneyhop.co/send-money-to-australia",
        category=Category.FINTECH,
        priority=2,
        send_currency="INR",
        receive_currency="AUD",
        fee=Decimal("0"),
        fee_note="₹0-200",
        eta_min=60,
        eta_max=12 * 60,
        eta_business_days=False,
        quotes_target_in_source=True,
        column_hints=("RATE",),
        currency_names=("AUSTRALIAN DOLLAR",),
        benchmark_only=True,
        notes=(
            "Direct competitor targeting Indian students. Tracked for rate "
            "benchmarking only — never surfaced in user-facing results, per "
            "the provider sheet's build tracker."
        ),
    ),
)


ALL_SITES: Tuple[SiteConfig, ...] = (
    *AU_BANKS, *IN_BANKS, *IN_FINTECH, *JS_CALCULATORS, *BENCHMARK,
)
