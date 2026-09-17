from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


# ── Provider / Compare schemas ────────────────────────────────────────────────

class ProviderQuote(BaseModel):
    """
    One provider's quote, normalized onto a comparable basis.

    The first block is the original contract and is unchanged, so existing
    clients keep working. Everything after it is additive.

    `send_amount` is what LEAVES THE SENDER'S ACCOUNT — fee included. Every
    provider is reported on that one basis, which is what makes
    `receive_amount` comparable across providers at all (see
    engine/normalize.py).
    """

    provider: str
    send_amount: float
    fee: float
    exchange_rate: float
    receive_amount: float
    currency_from: str
    currency_to: str
    transfer_time: str
    error: Optional[str] = None

    # ── Exact values ──────────────────────────────────────────────────────
    # Floats are fine for display but lose digits on rates like 83.4210000001.
    # These carry the full-precision decimal as a string, so a client that
    # cares (or a stored comparison replayed later) never inherits our
    # float rounding.
    exchange_rate_exact: Optional[str] = None
    receive_amount_exact: Optional[str] = None

    # ── Delivery speed ────────────────────────────────────────────────────
    # Numeric, so speed can be ranked and filtered instead of regex-matched.
    eta_min_minutes: Optional[int] = None
    eta_max_minutes: Optional[int] = None
    eta_is_business_days: bool = False

    # ── True cost ─────────────────────────────────────────────────────────
    # A provider advertising "zero fees" usually recovers it in the exchange
    # rate. Total cost = the visible fee PLUS the hidden FX markup, which is
    # the only number that actually ranks providers honestly.
    mid_market_rate: Optional[float] = None
    fx_markup_pct: Optional[float] = None
    fx_markup_cost: Optional[float] = None
    total_cost: Optional[float] = None
    total_cost_pct: Optional[float] = None

    # ── Who this provider is ──────────────────────────────────────────────
    #: "fintech" | "bank" | "neobank" | "legacy" | "broker" | "p2p"
    category: Optional[str] = None
    #: 1 = Critical .. 4 = Low, from the provider master list.
    priority: Optional[int] = None
    #: Known-bad pricing, kept in the comparison to show the gap. The big
    #: banks are here precisely because they are the expensive option.
    avoid: bool = False

    # ── Provenance ────────────────────────────────────────────────────────
    fee_model: Optional[str] = None            # "deducted" | "added"
    principal_amount: Optional[float] = None   # amount actually converted
    normalized: bool = False                   # basis was adjusted to compare
    pay_in_method: Optional[str] = None
    pay_out_method: Optional[str] = None
    service_name: Optional[str] = None
    is_promotional: bool = False
    rate_type: Optional[str] = None            # "base" | "promotional"


class SortMode(str, Enum):
    """
    The filters a user actually chooses between, the way Monito frames them.

    CHEAPEST is the honest default: it maximises what the recipient gets,
    which already accounts for fee and rate together. The others exist
    because "best" is genuinely personal — someone sending rent money cares
    about FASTEST, someone moving savings cares about BEST_RATE.
    """

    CHEAPEST = "cheapest"       # most money in the recipient's hands
    FASTEST = "fastest"         # earliest arrival
    LOWEST_FEE = "lowest_fee"   # smallest upfront fee
    BEST_RATE = "best_rate"     # smallest FX markup over mid-market
    BEST_VALUE = "best_value"   # blended cost-and-speed score


class CompareRequest(BaseModel):
    amount: float
    currency_from: str
    currency_to: str

    # ── Filters (all optional; defaults reproduce the old behaviour) ──────
    sort_by: SortMode = SortMode.CHEAPEST

    #: Drop quotes that cannot arrive within this many minutes.
    max_eta_minutes: Optional[int] = None

    #: Restrict to a funding method ("DEBIT", "BANK", ...) or a payout rail
    #: ("BANK_DEPOSIT", "CASH_PICKUP", ...). Case-insensitive.
    pay_in_method: Optional[str] = None
    pay_out_method: Optional[str] = None

    #: Promotional first-transfer rates are real, but not repeatable. Callers
    #: comparing ongoing cost should turn them off.
    include_promo: bool = True

    @field_validator("pay_in_method", "pay_out_method")
    @classmethod
    def normalize_method(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("max_eta_minutes")
    @classmethod
    def eta_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_eta_minutes must be positive")
        return v

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    @field_validator("currency_from", "currency_to")
    @classmethod
    def currency_must_be_uppercase(cls, v):
        return v.strip().upper()


class CompareResponse(BaseModel):
    """
    A ranked comparison.

    `quotes` holds only usable quotes, ordered by the requested `sort_by`.
    Providers that errored are named in `failed_providers` and detailed in
    `errors` — they are NOT mixed into `quotes`, because a failed provider
    used to enter the ranking with receive_amount 0.0 and drag every savings
    figure toward nonsense.
    """

    best_provider: ProviderQuote
    quotes: List[ProviderQuote]
    savings_vs_worst: float
    savings_vs_average: float
    request: CompareRequest
    failed_providers: List[str]

    # ── Additive ──────────────────────────────────────────────────────────
    #: Winner under each sort mode, as {mode: provider_name}. Lets the UI
    #: label "cheapest" and "fastest" without re-running the comparison.
    best_by: Dict[str, str] = {}

    #: Reference mid-market rate used for markup maths, when one was found.
    mid_market_rate: Optional[float] = None
    mid_market_rate_exact: Optional[str] = None
    mid_market_source: Optional[str] = None

    #: Full detail for providers that could not quote.
    errors: List[ProviderQuote] = []

    #: Quotes dropped by the request's filters (not failures).
    filtered_out: List[str] = []

    #: Providers that were never called, and why — {provider: reason}.
    #: Deliberately separate from `failed_providers`: "does not serve this
    #: corridor" and "needs an API key you have to apply for" are not
    #: outages, and showing them as failures makes a healthy system look
    #: broken and hides the ones that genuinely broke.
    unavailable_providers: Dict[str, str] = {}


# ── User schemas ──────────────────────────────────────────────────────────────

class UserSync(BaseModel):
    """Called after Clerk sign-up to upsert the user row."""
    clerk_id: str
    email: str
    full_name: Optional[str] = None


class UserRead(BaseModel):
    id: int
    clerk_user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    country: Optional[str] = None
    university: Optional[str] = None
    whatsapp_number: Optional[str] = None
    home_currency: Optional[str] = None
    corridor_from: Optional[str] = None
    corridor_to: Optional[str] = None
    is_onboarded: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    country: Optional[str] = None
    university: Optional[str] = None
    home_currency: Optional[str] = None
    corridor_from: Optional[str] = None
    corridor_to: Optional[str] = None
    is_onboarded: Optional[bool] = None


# ── Onboarding schema ─────────────────────────────────────────────────────────

class OnboardingComplete(BaseModel):
    country: str
    university: Optional[str] = None
    whatsapp_number: Optional[str] = None
    home_currency: Optional[str] = None
    corridor_from: Optional[str] = None
    corridor_to: Optional[str] = None


# ── Legacy profile schemas (kept for backwards compatibility) ─────────────────

class ProfileCreate(BaseModel):
    country: str
    university: str
    whatsapp_number: Optional[str] = None


class ProfileResponse(BaseModel):
    id: int
    clerk_user_id: str
    email: Optional[str] = None
    country: Optional[str] = None
    university: Optional[str] = None
    whatsapp_number: Optional[str] = None
    is_onboarded: bool
    is_new_user: bool = False

    class Config:
        from_attributes = True


class UserStatusResponse(BaseModel):
    """Lightweight check — does this Clerk user already have a saved profile?"""
    exists: bool
    is_onboarded: bool = False


# ──────────────── Comparison schemas ────────────────────────────────────────────────────────

class ComparisonCreate(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    results_json: str   # JSON string of the provider results array


class ComparisonRead(BaseModel):
    id: int
    clerk_user_id: Optional[str] = None
    amount: float
    from_currency: str
    to_currency: str
    results_json: str
    created_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────── Rate Alert schemas ────────────────────────────────────────────────────────

class RateAlertCreate(BaseModel):
    from_currency: str
    to_currency: str
    amount: float
    target_rate: float
    provider: Optional[str] = None
    notify_email: bool = True
    notify_whatsapp: bool = False


class RateAlertRead(BaseModel):
    id: int
    clerk_user_id: str
    from_currency: str
    to_currency: str
    amount: float
    target_rate: float
    provider: Optional[str] = None
    notify_email: bool
    notify_whatsapp: bool
    is_active: bool
    last_triggered: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RateAlertUpdate(BaseModel):
    target_rate: Optional[float] = None
    is_active: Optional[bool] = None
    notify_email: Optional[bool] = None
    notify_whatsapp: Optional[bool] = None
    provider: Optional[str] = None


class ContactMessage(BaseModel):
    name: str
    email: str
    subject: str
    message: str


# ── Click tracking ────────────────────────────────────────────────────────────

class ClickCreate(BaseModel):
    provider: str
    from_currency: str
    to_currency: str
    amount: float
