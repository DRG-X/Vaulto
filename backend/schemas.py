import re

from pydantic import BaseModel, field_validator, model_validator
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


class ProviderInfo(BaseModel):
    """
    One provider as the registry knows it — no rates, no network.

    Lets the client render the full directory from the same source the engine
    ranks from. The alternative, a hardcoded list in the frontend, went stale
    the moment the registry grew past three providers.
    """

    name: str
    slug: str
    category: str
    integration: str            # public_api | partner_api | partial_api | scrape
    priority: int               # 1 = Critical .. 4 = Low
    corridors: List[str]        # e.g. ["AUD->INR"] or ["*->*"]
    cannot_send_from: List[str] = []
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    limits_currency: Optional[str] = None
    requires_credentials: List[str] = []
    is_configured: bool = True
    avoid: bool = False
    rate_reference_only: bool = False
    needs_browser: bool = False
    website: Optional[str] = None
    notes: Optional[str] = None


class ProviderListResponse(BaseModel):
    providers: List[ProviderInfo]
    total: int
    #: Providers tracked for benchmarking are excluded by design, and the count
    #: is reported so the omission is visible rather than looking like a bug.
    hidden_benchmark: int = 0


# ── User schemas ──────────────────────────────────────────────────────────────

# Shared field normalisers. Onboarding and the settings page write the same
# columns, so they normalise identically — otherwise "gbp" from one screen and
# "GBP" from the other are two different corridors to every query that follows.

def normalize_country(v: Optional[str], *, required: bool = False) -> Optional[str]:
    v = (v or "").strip().upper()
    if not v:
        if required:
            raise ValueError("country is required")
        return None
    if not (len(v) == 2 and v.isalpha()):
        raise ValueError("country must be a 2-letter ISO code, e.g. 'GB'")
    return v


def normalize_currency(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip().upper()
    if not v:
        return None
    if not (len(v) == 3 and v.isalpha()):
        raise ValueError("currency must be a 3-letter ISO code, e.g. 'GBP'")
    return v


def normalize_phone(v: Optional[str]) -> Optional[str]:
    """
    Store one canonical shape (+ digits) so the alert sender never has to guess
    whether "+44 7700 900 123" and "+447700900123" are the same number.
    """
    if v is None:
        return None
    compact = re.sub(r"[\s()\-.]", "", v.strip())
    if not compact:
        return None
    if not compact.startswith("+"):
        compact = "+" + compact
    digits = compact[1:]
    if not digits.isdigit() or not (7 <= len(digits) <= 15):
        raise ValueError("whatsapp_number must be 7-15 digits, e.g. '+447700900123'")
    return compact


class UserSync(BaseModel):
    """
    Called after Supabase sign-up / sign-in to upsert the user row.

    Every field is optional on purpose. The row is keyed off the `sub` claim of
    the verified JWT, never off the body, so a client that calls sync one tick
    before Supabase has hydrated its user object still syncs the right account
    instead of being rejected. `supabase_id` is accepted when the caller knows
    it and is then checked against the token — a mismatch is a real error.
    """
    supabase_id: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None

    @field_validator("supabase_id", "email", "full_name")
    @classmethod
    def _blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class UserRead(BaseModel):
    id: int
    supabase_user_id: str
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
    """
    Partial update from the settings page. Values are normalised to the same
    shapes onboarding stores, so a corridor saved in settings and one saved in
    onboarding are byte-identical.
    """
    full_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    country: Optional[str] = None
    university: Optional[str] = None
    home_currency: Optional[str] = None
    corridor_from: Optional[str] = None
    corridor_to: Optional[str] = None
    is_onboarded: Optional[bool] = None

    @field_validator("home_currency", "corridor_from", "corridor_to")
    @classmethod
    def _currency(cls, v: Optional[str]) -> Optional[str]:
        return normalize_currency(v)

    @field_validator("whatsapp_number")
    @classmethod
    def _whatsapp(cls, v: Optional[str]) -> Optional[str]:
        return normalize_phone(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: Optional[str]) -> Optional[str]:
        return normalize_country(v)

    @model_validator(mode="after")
    def _corridor_legs_differ(self) -> "UserUpdate":
        if self.corridor_from and self.corridor_to and self.corridor_from == self.corridor_to:
            raise ValueError("corridor_from and corridor_to must be different currencies")
        return self


# ── Onboarding schema ─────────────────────────────────────────────────────────

class OnboardingComplete(BaseModel):
    """
    Final step of the onboarding wizard.

    `country` is where the user SENDS FROM (where they live or study), which is
    also the country their university is in. `corridor_from` is that country's
    currency and `corridor_to` / `home_currency` belong to the country they send
    money home to.

    The two corridor legs are validated against each other here rather than in
    the route: a corridor whose legs are equal is not a comparison the engine
    can answer, and storing one turns every "compare now" link on the dashboard
    into an error page.
    """
    country: str
    university: Optional[str] = None
    whatsapp_number: Optional[str] = None
    home_currency: Optional[str] = None
    corridor_from: Optional[str] = None
    corridor_to: Optional[str] = None

    @field_validator("country")
    @classmethod
    def _iso_country(cls, v: str) -> str:
        return normalize_country(v, required=True)

    @field_validator("home_currency", "corridor_from", "corridor_to")
    @classmethod
    def _iso_currency(cls, v: Optional[str]) -> Optional[str]:
        return normalize_currency(v)

    @field_validator("university")
    @classmethod
    def _trim_university(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v[:200] or None

    @field_validator("whatsapp_number")
    @classmethod
    def _e164(cls, v: Optional[str]) -> Optional[str]:
        return normalize_phone(v)

    @model_validator(mode="after")
    def _corridor_legs_differ(self) -> "OnboardingComplete":
        if self.corridor_from and self.corridor_to and self.corridor_from == self.corridor_to:
            raise ValueError("corridor_from and corridor_to must be different currencies")
        return self


# ── Legacy profile schemas (kept for backwards compatibility) ─────────────────

class ProfileCreate(BaseModel):
    country: str
    university: str
    whatsapp_number: Optional[str] = None


class ProfileResponse(BaseModel):
    id: int
    supabase_user_id: str
    email: Optional[str] = None
    country: Optional[str] = None
    university: Optional[str] = None
    whatsapp_number: Optional[str] = None
    is_onboarded: bool
    is_new_user: bool = False

    class Config:
        from_attributes = True


class UserStatusResponse(BaseModel):
    """Lightweight check — does this Supabase user already have a saved profile?"""
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
    supabase_user_id: Optional[str] = None
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
    #: None = any provider. When set, the alert watches THAT provider's rate.
    provider: Optional[str] = None
    #: None = any rail. Canonical name, e.g. "BANK_DEPOSIT" or "UPI".
    pay_out_method: Optional[str] = None
    notify_email: bool = True
    notify_whatsapp: bool = False

    @field_validator("pay_out_method")
    @classmethod
    def normalize_rail(cls, v):
        return v.strip().upper() if isinstance(v, str) and v.strip() else None


class RateAlertRead(BaseModel):
    id: int
    supabase_user_id: str
    from_currency: str
    to_currency: str
    amount: float
    target_rate: float
    provider: Optional[str] = None
    pay_out_method: Optional[str] = None
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
    pay_out_method: Optional[str] = None


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
