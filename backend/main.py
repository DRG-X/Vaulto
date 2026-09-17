import json
import logging
import sys
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env before any other module reads environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Make sure backend root is on the path so relative imports work cleanly
sys.path.insert(0, os.path.dirname(__file__))

from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import ValidationError

from schemas import (
    CompareRequest, CompareResponse,
    ProfileCreate, ProfileResponse, UserStatusResponse,
    UserSync, UserRead, UserUpdate,
    OnboardingComplete,
    ComparisonCreate, ComparisonRead, SortMode,
    RateAlertCreate, RateAlertRead, RateAlertUpdate,
    ContactMessage,
    ClickCreate,
)
from decimal import Decimal

from engine.comparator import QuotePools, compare, fetch_pools, rank_pools

import models
from database import Base, engine, get_db
from auth import verify_clerk_token, verify_admin_token
from cache import get_cached_rates, set_cached_rates, init_cache, close_cache
from scheduler import start_scheduler, stop_scheduler


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("flint")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared resources on startup; clean up on shutdown."""
    await init_cache()   # connect Redis + PING test
    from models import User, Comparison, RateAlert, ProviderClick  # noqa — ensures models registered
    Base.metadata.create_all(bind=engine)           # safety net: create tables if not present
    logger.info("CORS allowed origins: %s", ALLOWED_ORIGINS)
    start_scheduler()    # background alert checker — every 15 min
    yield
    stop_scheduler()     # graceful shutdown
    await close_cache()  # graceful shutdown


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Flint API",
    description="Real-time international money transfer comparison engine",
    version="1.0.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting (slowapi) ───────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

def _real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")

limiter = Limiter(key_func=_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY ROUTES  (keep for backwards compatibility with existing frontend)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok", "service": "flint-api"}

# @app.get("/user/onboarding" , response_model = UserStatusResponse)
# def onboarding_status(
    

@app.get("/user/status", response_model=UserStatusResponse)
def get_user_status(
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    return {
        "exists": user is not None,
        "is_onboarded": user.is_onboarded if user else False
    }


@app.get("/user/profile", response_model=ProfileResponse)
def get_user_profile(
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found")
    return user


@app.post("/user/profile", response_model=ProfileResponse, status_code=201)
def create_user_profile(
    profile_data: ProfileCreate,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    clerk_id = user_auth["clerk_user_id"]
    user = db.query(models.User).filter(models.User.clerk_user_id == clerk_id).first()

    if user:
        user.is_new_user = False
        return user

    new_user = models.User(
        clerk_user_id=clerk_id,
        email=user_auth.get("email"),
        country=profile_data.country,
        university=profile_data.university,
        whatsapp_number=profile_data.whatsapp_number,
        is_onboarded=True,
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        logger.exception("Failed to insert user profile for clerk_id=%s", clerk_id)
        raise HTTPException(status_code=500, detail="Database insertion failed")

    new_user.is_new_user = True
    return new_user


@app.post("/compare", response_model=CompareResponse)
@limiter.limit("20/minute")
async def compare_providers(request: Request, body: CompareRequest):
    logger.info(f"compare request: {body.amount} {body.currency_from} → {body.currency_to}")
    try:
        result = await compare(body)
        logger.info(
            f"compare done: best={result.best_provider.provider} "
            f"({result.best_provider.receive_amount} {body.currency_to}), "
            f"failed={result.failed_providers}"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unexpected error in /compare")
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/api/contact", status_code=200)
async def submit_contact(body: ContactMessage):
    logger.info(
        "CONTACT FORM — name=%s email=%s subject=%s",
        body.name, body.email, body.subject
    )
    logger.info("CONTACT MESSAGE — %s", body.message[:500])
    return {"status": "received"}


# ═══════════════════════════════════════════════════════════════════════════════
# /api/users  — user management
# ═══════════════════════════════════════════════════════════════════════════════

users_router = APIRouter(prefix="/api/users", tags=["users"])

@users_router.post("/sync", response_model=UserRead)
def sync_user(body: UserSync, user_auth: dict = Depends(verify_clerk_token), db: Session = Depends(get_db)):
    """
    Called after Clerk sign-up/sign-in from post-auth.js.
    Creates the user row if it doesn't exist, returns the user either way.
    """
    if body.clerk_id != user_auth["clerk_user_id"]:
        raise HTTPException(status_code=403, detail="Cannot sync another user's account")
    user = db.query(models.User).filter(models.User.clerk_user_id == body.clerk_id).first()
    if user:
        # Update name/email if provided
        if body.full_name and not user.full_name:
            user.full_name = body.full_name
        if body.email and not user.email:
            user.email = body.email
        db.commit()
        db.refresh(user)
        return user

    new_user = models.User(
        clerk_user_id=body.clerk_id,
        email=body.email,
        full_name=body.full_name,
        is_onboarded=False,
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        logger.exception("sync_user: failed for clerk_id=%s", body.clerk_id)
        raise HTTPException(status_code=500, detail="Failed to sync user")
    return new_user


@users_router.get("/me", response_model=UserRead)
def get_me(
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@users_router.patch("/me", response_model=UserRead)
def update_me(
    body: UserUpdate,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update user")
    return user


app.include_router(users_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/onboarding
# ═══════════════════════════════════════════════════════════════════════════════

onboarding_router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@onboarding_router.post("/complete", response_model=UserRead)
def complete_onboarding(
    body: OnboardingComplete,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """
    Saves all onboarding fields and marks onboarding_done = True.
    Called on final step submit of the onboarding wizard.
    """
    clerk_id = user_auth["clerk_user_id"]
    user = db.query(models.User).filter(models.User.clerk_user_id == clerk_id).first()

    if not user:
        # Auto-create if sync call was missed
        user = models.User(clerk_user_id=clerk_id, email=user_auth.get("email"))
        db.add(user)

    user.country         = body.country
    user.university      = body.university
    user.whatsapp_number = body.whatsapp_number
    user.home_currency   = body.home_currency
    user.corridor_from   = body.corridor_from
    user.corridor_to     = body.corridor_to
    user.is_onboarded    = True

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        logger.exception("complete_onboarding: failed for clerk_id=%s", clerk_id)
        raise HTTPException(status_code=500, detail="Failed to save onboarding data")
    return user


app.include_router(onboarding_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/rates  — public rate comparison endpoint (GET wrapper around comparator)
# ═══════════════════════════════════════════════════════════════════════════════

rates_router = APIRouter(prefix="/api/rates", tags=["rates"])


@rates_router.get("")
@limiter.limit("30/minute")  # 30 requests per minute per IP
async def get_rates(
    request: Request,
    from_currency: str = Query(..., alias="from"),
    to_currency: str   = Query(..., alias="to"),
    amount: float      = Query(..., gt=0),
    sort_by: SortMode  = Query(SortMode.CHEAPEST, description="cheapest | fastest | lowest_fee | best_rate | best_value"),
    max_eta_minutes: Optional[int] = Query(None, gt=0, description="Drop quotes that cannot arrive this fast"),
    pay_in_method: Optional[str]   = Query(None, description="e.g. BANK, DEBIT, CREDIT"),
    pay_out_method: Optional[str]  = Query(None, description="e.g. BANK_DEPOSIT, CASH_PICKUP"),
    include_promo: bool = Query(True, description="Include first-transfer promotional rates"),
):
    """
    Public GET endpoint for the results page.

    Checks Redis cache first, keyed on the EXACT amount (it used to bucket to
    the nearest 50, which served a comparison computed for a different amount
    than the one asked for). Falls back to the live comparator on a miss.

    Returns { results, best_provider, best_by, mid_market_rate, savings_*,
    failed_providers, filtered_out, stale, no_data, cached }.
    """
    from_upper = from_currency.upper()
    to_upper   = to_currency.upper()

    try:
        req = CompareRequest(
            amount=amount,
            currency_from=from_upper,
            currency_to=to_upper,
            sort_by=sort_by,
            max_eta_minutes=max_eta_minutes,
            pay_in_method=pay_in_method,
            pay_out_method=pay_out_method,
            include_promo=include_promo,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # What we cache is the PROVIDER DATA, not the ranked response.
    #
    # Filters and sort modes never change what we ask the providers for, only
    # how their answers are presented — so caching the ranked output would key
    # on five extra fields and turn nearly every request into a fresh fan-out
    # to APIs that rate-limit. Caching the fetch instead means one upstream
    # round per (corridor, amount), and every filter combination re-ranks off
    # it for free, in microseconds.
    cached = await get_cached_rates(from_upper, to_upper, amount)
    was_cached = False
    try:
        if cached:
            pools = QuotePools.from_dict(cached)
            was_cached = True
            logger.info("get_rates: cache HIT for %s→%s %s", from_upper, to_upper, amount)
        else:
            pools = await fetch_pools(Decimal(str(amount)), from_upper, to_upper)
            await set_cached_rates(from_upper, to_upper, amount, pools.to_dict())
    except Exception:
        logger.exception("get_rates: provider fetch failed")
        return {
            "results": [], "stale": False, "no_data": True,
            "failed_providers": [], "filtered_out": [],
            "reason": "Internal error", "cached": False,
        }

    try:
        result = rank_pools(pools, req)
        response = {
            "results": [q.model_dump() for q in result.quotes],
            "best_provider": result.best_provider.provider,
            "best_by": result.best_by,
            "mid_market_rate": result.mid_market_rate,
            "mid_market_rate_exact": result.mid_market_rate_exact,
            "mid_market_source": result.mid_market_source,
            "savings_vs_worst": result.savings_vs_worst,
            "savings_vs_average": result.savings_vs_average,
            "failed_providers": result.failed_providers,
            "errors": [q.model_dump() for q in result.errors],
            "filtered_out": result.filtered_out,
            "unavailable_providers": result.unavailable_providers,
            "sort_by": sort_by.value,
            "stale": False,
            "no_data": False,
            "cached": was_cached,
        }
        return response
    except ValueError as e:
        # No provider could quote, or every one was filtered out. Surface the
        # reason instead of an anonymous empty list — "no results" and "your
        # filter excluded everything" need different fixes from the user.
        return {
            "results": [], "stale": False, "no_data": True,
            "failed_providers": [], "filtered_out": [],
            "reason": str(e), "cached": False,
        }
    except Exception:
        logger.exception("get_rates: unexpected error")
        return {
            "results": [], "stale": False, "no_data": True,
            "failed_providers": [], "filtered_out": [],
            "reason": "Internal error", "cached": False,
        }


app.include_router(rates_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/comparisons
# ═══════════════════════════════════════════════════════════════════════════════

comparisons_router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


@comparisons_router.post("", response_model=ComparisonRead, status_code=201)
def save_comparison(
    body: ComparisonCreate,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    record = models.Comparison(
        clerk_user_id=user_auth["clerk_user_id"],
        amount=body.amount,
        from_currency=body.from_currency.upper(),
        to_currency=body.to_currency.upper(),
        results_json=body.results_json,
    )
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save comparison")
    return record


@comparisons_router.get("", response_model=list[ComparisonRead])
def list_comparisons(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    offset = (page - 1) * limit
    rows = (
        db.query(models.Comparison)
        .filter(models.Comparison.clerk_user_id == user_auth["clerk_user_id"])
        .order_by(models.Comparison.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows


app.include_router(comparisons_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/alerts
# ═══════════════════════════════════════════════════════════════════════════════

alerts_router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@alerts_router.post("", response_model=RateAlertRead, status_code=201)
def create_alert(
    body: RateAlertCreate,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    alert = models.RateAlert(
        clerk_user_id   = user_auth["clerk_user_id"],
        from_currency   = body.from_currency.upper(),
        to_currency     = body.to_currency.upper(),
        amount          = body.amount,
        target_rate     = body.target_rate,
        provider        = body.provider,
        notify_email    = body.notify_email,
        notify_whatsapp = body.notify_whatsapp,
    )
    db.add(alert)
    try:
        db.commit()
        db.refresh(alert)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create alert")
    return alert


@alerts_router.get("", response_model=list[RateAlertRead])
def list_alerts(
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    return (
        db.query(models.RateAlert)
        .filter(models.RateAlert.clerk_user_id == user_auth["clerk_user_id"])
        .order_by(models.RateAlert.created_at.desc())
        .all()
    )


@alerts_router.patch("/{alert_id}", response_model=RateAlertRead)
def update_alert(
    alert_id: int,
    body: RateAlertUpdate,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    alert = db.query(models.RateAlert).filter(
        models.RateAlert.id == alert_id,
        models.RateAlert.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(alert, field, value)

    try:
        db.commit()
        db.refresh(alert)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update alert")
    return alert


@alerts_router.delete("/{alert_id}", status_code=204)
def delete_alert(
    alert_id: int,
    user_auth: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    alert = db.query(models.RateAlert).filter(
        models.RateAlert.id == alert_id,
        models.RateAlert.clerk_user_id == user_auth["clerk_user_id"]
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    db.delete(alert)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete alert")

app.include_router(alerts_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/clicks  — affiliate click tracking (anonymous-safe)
# ═══════════════════════════════════════════════════════════════════════════════

_click_bearer = HTTPBearer(auto_error=False)   # don't reject unauthenticated requests

clicks_router = APIRouter(prefix="/api/clicks", tags=["clicks"])


@clicks_router.post("", status_code=201)
async def track_click(
    body: ClickCreate,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_click_bearer),
):
    """
    Fire-and-forget click event from the results page.
    Authenticated users get their clerk_user_id attached; anonymous clicks are
    stored with clerk_user_id=None — both are valid for revenue analytics.
    """
    clerk_user_id = None
    if credentials:
        try:
            payload = verify_clerk_token(credentials)
            clerk_user_id = payload.get("clerk_user_id")
        except Exception:
            pass  # anonymous click — perfectly fine

    click = models.ProviderClick(
        clerk_user_id=clerk_user_id,
        provider=body.provider,
        from_currency=body.from_currency.upper(),
        to_currency=body.to_currency.upper(),
        amount=body.amount,
    )
    db.add(click)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.error("track_click: DB commit failed for provider=%s", body.provider)
    return {"tracked": True}


app.include_router(clicks_router)


# ═══════════════════════════════════════════════════════════════════════════════
# /api/admin
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/stats")
def get_admin_stats(
    user_auth: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    total_users = db.query(models.User).count()
    total_comparisons = db.query(models.Comparison).count()
    total_alerts = db.query(models.RateAlert).count()
    return {
        "total_users": total_users,
        "total_comparisons": total_comparisons,
        "total_alerts": total_alerts,
    }
