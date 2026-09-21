"""
scheduler.py — the rate-alert check, and everything it takes to deliver one.

The name is historical: there is no scheduler in here any more. This module used
to own an APScheduler job that ticked every 15 minutes inside the API process,
which required a process that stays alive between ticks. On Cloud Run, which
scales to zero when no request is in flight, that process does not exist — the
ticks simply never happened and alerts silently stopped being delivered.

`check_alerts()` is now driven from outside, by Supabase Cron calling
`POST /internal/check-alerts` every 15 minutes (see main.py). The schedule lives
in the database, where it survives a deployment that has no instances running,
and the work itself is unchanged.
"""

import logging
import datetime

from sqlalchemy.orm import Session

import notifications
import supabase_client
from database import SessionLocal
from models import RateAlert, User
from engine.comparator import QuotePools, fetch_pools
from cache import get_cached_rates, set_cached_rates
from money import D

logger = logging.getLogger(__name__)


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
    """
    Check every active alert against live rates, and deliver the ones that hit.

    Called once per tick by `POST /internal/check-alerts`, which Supabase Cron
    requests every 15 minutes. It opens and closes its own database session, so
    it is safe to call from a request handler.
    """
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
                        await _fire(alert, quote.exchange_rate, quote.provider, db)

            except Exception as exc:
                # Roll back before the next corridor: a failed commit leaves
                # the session in a state where every later query raises, so
                # one bad corridor used to take out the rest of the run.
                db.rollback()
                logger.exception("Alert check failed for %s→%s: %s", from_cur, to_cur, exc)

    finally:
        db.close()

    logger.info("Alert checker: run complete")


async def _fire(alert: RateAlert, rate: float, provider: str, db) -> bool:
    """
    Deliver a triggered alert and pause it — but only if delivery worked.

    The alert used to be paused unconditionally, right after a notification
    call that swallowed its own errors. A missing API key or an unverified
    sending domain therefore consumed the alert AND sent nothing: the user
    lost the notification and the watch that would have produced the next one,
    silently. An alert is the user's property; a failure on our side must not
    spend it.

    Returns True when the user was actually notified.
    """
    sent = await send_alert_notification(alert, rate, provider, db)

    if not sent:
        logger.error(
            "Alert %s hit its target but could not be delivered — leaving it "
            "active to retry on the next run",
            alert.id,
        )
        return False

    alert.last_triggered = datetime.datetime.utcnow()
    alert.is_active = False  # auto-pause after a DELIVERED trigger, to prevent spam
    db.commit()
    return True


async def _address_for(alert: RateAlert, user: User, db) -> str:
    """
    The address to mail, asking Supabase for it if we never captured one.

    A Supabase access token carries the address, so `/api/users/sync` stores it
    on first sign-in and this fallback is rarely needed. It still is for rows
    that predate that — every account carried over from Clerk, whose session
    token had no email claim and left `users.email` NULL. Persisting what the
    lookup finds means it happens once per user, not once per alert.
    """
    if user.email:
        return user.email

    address = await supabase_client.fetch_primary_email(alert.supabase_user_id)
    if not address:
        return ""

    user.email = address
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Could not persist the email address for %s", alert.supabase_user_id)
    return address


async def send_alert_notification(
    alert: RateAlert, current_rate: float, provider: str, db: Session
) -> bool:
    """
    Notify the user that their target was reached.

    Returns True only when a notification actually went out. The caller uses
    that to decide whether the alert has been spent.
    """
    user = db.query(User).filter(User.supabase_user_id == alert.supabase_user_id).first()
    if not user:
        logger.warning(
            "Alert %s: no user found for supabase_user_id=%s",
            alert.id, alert.supabase_user_id,
        )
        return False

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
        f"\U0001f3af Rate Alert Hit!\n\n"
        f"Your target: 1 {alert.from_currency} = {alert.target_rate} {alert.to_currency}\n"
        f"{rate_line}\n"
        f"Send money now at vaulto.in"
        f"\n\nThis alert has been automatically paused.\n"
        f"Visit https://vaulto.in/alerts to re-enable it or set a new target."
    )

    if alert.notify_whatsapp and not alert.notify_email:
        # The UI offers this toggle; nothing implements it. Saying so is better
        # than returning True and letting the alert be marked delivered.
        logger.error(
            "Alert %s asked for WhatsApp only, which is not implemented — "
            "no notification sent",
            alert.id,
        )
        return False

    if not alert.notify_email:
        logger.warning("Alert %s has no enabled notification channel", alert.id)
        return False

    address = await _address_for(alert, user, db)
    if not address:
        logger.error(
            "Alert %s triggered but no email address is on file for %s, and "
            "Supabase did not supply one — nothing sent",
            alert.id, alert.supabase_user_id,
        )
        return False

    try:
        await notifications.send_email(
            address,
            f"Rate alert triggered \u2014 {alert.from_currency}\u2192{alert.to_currency} (now paused)",
            message,
        )
    except notifications.EmailNotConfigured as exc:
        logger.error("Alert %s: %s", alert.id, exc)
        return False
    except notifications.EmailSendFailed as exc:
        logger.error("Alert %s: email delivery failed \u2014 %s", alert.id, exc)
        return False

    logger.info("Alert %s delivered to %s", alert.id, address)
    return True
