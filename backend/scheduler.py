import logging
import datetime
import base64

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from database import SessionLocal
from models import RateAlert, User
from engine.comparator import QuotePools, fetch_pools
from cache import get_cached_rates, set_cached_rates
from money import D
import os

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


def _quote_for_alert(pools, alert: RateAlert):
    """
    The quote an alert is actually watching, or None.

    Takes the FULL option pools, not a ranked comparison. `compare()` collapses
    each provider to a single option chosen by the active sort, so a
    "Remitly via UPI" alert looking at that result would only ever see
    Remitly's bank-deposit row and report "not available" forever — the rail it
    watches is in the pool but not in the ranked output.

    `RateAlert.provider` was also stored but never read: every alert fired on
    whichever provider happened to be best, so an alert set for "Wise at 55"
    would fire on Remitly hitting 55 — a notification about a rate the user
    never asked to be told about, on a provider they did not choose.

    Narrowing to nothing returns None rather than falling back to the best
    quote. A fallback is what caused that bug; silence is the honest answer
    when the thing being watched did not quote.
    """
    candidates = [q for options in pools.values() for q in options]

    if alert.provider:
        wanted = alert.provider.strip().lower()
        candidates = [q for q in candidates if q.provider.strip().lower() == wanted]

    if getattr(alert, "pay_out_method", None):
        rail = alert.pay_out_method.strip().upper()
        candidates = [
            q for q in candidates
            if (q.pay_out_method or "").strip().upper() == rail
        ]

    if not candidates:
        return None

    # Best rate among what is left — the number the alert's threshold means.
    return max(candidates, key=lambda q: q.exchange_rate)


async def check_alerts():
    """Run every 15 minutes. Check all active alerts against live rates."""
    logger.info("Alert checker: starting run")
    db: Session = SessionLocal()
    try:
        active_alerts = db.query(RateAlert).filter(RateAlert.is_active == True).all()  # noqa: E712

        if not active_alerts:
            logger.info("Alert checker: no active alerts — skipping")
            return

        # Group by corridor to avoid redundant API calls. The amount is part of
        # the key because provider fees are tiered and rates are amount-banded:
        # quoting a 10,000 alert off a 500 comparison would watch a price that
        # alert will never be offered.
        corridors: dict[tuple[str, str, float], list[RateAlert]] = {}
        for alert in active_alerts:
            key = (alert.from_currency, alert.to_currency, float(alert.amount))
            corridors.setdefault(key, []).append(alert)

        for (from_cur, to_cur, amount), alerts in corridors.items():
            try:
                # Same cached fetch the public API uses. Alerts run every 15
                # minutes across every distinct amount, so going straight to the
                # providers would multiply the fan-out by the number of alert
                # amounts — into APIs that rate-limit.
                cached = await get_cached_rates(from_cur, to_cur, amount)
                if cached:
                    pools_obj = QuotePools.from_dict(cached)
                else:
                    pools_obj = await fetch_pools(D(amount), from_cur, to_cur)
                    await set_cached_rates(from_cur, to_cur, amount, pools_obj.to_dict())

                for alert in alerts:
                    quote = _quote_for_alert(pools_obj.pools, alert)
                    if quote is None:
                        # The provider or rail this alert watches did not quote
                        # this round. Staying silent is correct — firing on
                        # someone else's rate would be a false alarm.
                        logger.info(
                            "Alert %s: %s%s not available this round",
                            alert.id, alert.provider or "any provider",
                            f" via {alert.pay_out_method}" if alert.pay_out_method else "",
                        )
                        continue

                    if quote.exchange_rate >= alert.target_rate:
                        logger.info(
                            "Alert %s triggered: %s at %.4f >= %.4f",
                            alert.id, quote.provider, quote.exchange_rate, alert.target_rate,
                        )
                        await send_alert_notification(
                            alert, quote.exchange_rate, quote.provider, db
                        )
                        alert.last_triggered = datetime.datetime.utcnow()
                        alert.is_active = False  # auto-pause after first trigger to prevent spam
                        db.commit()

            except Exception as exc:
                logger.error("Alert check failed for %s→%s: %s", from_cur, to_cur, exc)

    finally:
        db.close()

    logger.info("Alert checker: run complete")


async def send_alert_notification(
    alert: RateAlert, current_rate: float, provider: str, db: Session
) -> None:
    """Send email notification when a target rate is reached."""
    user = db.query(User).filter(User.clerk_user_id == alert.clerk_user_id).first()
    if not user:
        logger.warning("Alert %s: no user found for clerk_user_id=%s", alert.id, alert.clerk_user_id)
        return

    # Describe what was ACTUALLY watched. A provider- or rail-scoped alert is
    # not a claim about the market: saying "best provider right now: Wise"
    # when the alert only ever looked at Wise would assert something we did
    # not check, and could be plainly false with a better provider alongside.
    scope = []
    if alert.provider:
        scope.append(alert.provider)
    if getattr(alert, "pay_out_method", None):
        scope.append(alert.pay_out_method.replace("_", " ").lower())
    scoped = " via ".join(scope)

    rate_line = (
        f"{scoped} is now at: 1 {alert.from_currency} = {current_rate:.4f} {alert.to_currency}\n"
        if scoped
        else f"Best rate right now: 1 {alert.from_currency} = {current_rate:.4f} {alert.to_currency}\n"
             f"Best provider right now: {provider}\n"
    )

    message = (
        f"🎯 Rate Alert Hit!\n\n"
        f"Your target: 1 {alert.from_currency} = {alert.target_rate} {alert.to_currency}\n"
        f"{rate_line}\n"
        f"Send money now at vaulto.in"
        f"\n\nThis alert has been automatically paused.\n"
        f"Visit https://vaulto.in/alerts to re-enable it or set a new target."
    )

    if alert.notify_email and user.email:
        await send_email_notification(user.email, message, alert)


async def send_email_notification(email: str, message: str, alert: RateAlert) -> None:
    """Send via Resend (free tier: 100 emails/day, 3 000/month)."""
    import resend  # lazy import — only needed when emails fire

    resend.api_key = os.getenv("RESEND_API_KEY", "")
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set — email not sent")
        return

    try:
        resend.Emails.send({
            "from": "alerts@vaulto.in",
            "to": email,
            "subject": f"Rate alert triggered — {alert.from_currency}→{alert.to_currency} (now paused)",
            "text": message,
        })
        logger.info("Email notification sent to %s for alert %s", email, alert.id)
    except Exception as exc:
        logger.error("Email send failed for alert %s: %s", alert.id, exc)


def start_scheduler() -> None:
    """Register the alert-checker job and start the scheduler."""
    scheduler.add_job(
        check_alerts,
        trigger="interval",
        minutes=15,
        id="alert_checker",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Alert scheduler started — checking every 15 minutes")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler (called on app shutdown)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Alert scheduler stopped")
