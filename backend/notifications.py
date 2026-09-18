"""
notifications.py — getting a triggered alert to the person who asked for it.

Why this is its own module, and why it raises
---------------------------------------------
The previous implementation lived inside the scheduler, called the `resend`
SDK, and caught every exception to log a warning. That reads as defensive, but
the caller could not tell a delivered mail from a dropped one — and it used
the call's return to decide whether to pause the alert. A missing API key, an
unverified sending domain, or a Resend outage therefore consumed the user's
alert and sent nothing, with an INFO-level log line saying the run completed.

So every failure here raises. The caller decides what a failure means, and in
this codebase it means "leave the alert armed and try again next run".

Transport
---------
This calls Resend's REST API over the httpx client the rest of the app already
uses, rather than the `resend` SDK. The SDK's `Emails.send` is a synchronous,
blocking HTTP call; the alert checker runs on the API server's own event loop,
so every send stalled every in-flight request for the duration. Going direct
also drops a dependency and makes the failure body readable, which matters
because the most likely production failure — an unverified sending domain —
is only explained in that body.

Free-tier notes
---------------
Resend's free tier is 3,000 emails/month and 100/day, which is the limit that
bites first: 100/day is a hard ceiling on how many alerts can fire in a day.
`ALERT_FROM_EMAIL` must be on a domain verified in the Resend dashboard.
Until a domain is verified, Resend only accepts `onboarding@resend.dev` as the
sender, and only to the account owner's own address — enough to prove the
pipeline works, not enough to serve users.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"

#: Resend's own default sender. Works without verifying a domain, but only
#: delivers to the Resend account owner — a smoke-test sender, not a real one.
FALLBACK_FROM = "Vaulto Alerts <onboarding@resend.dev>"

TIMEOUT = 15


class EmailNotConfigured(RuntimeError):
    """No API key. Nothing was attempted."""


class EmailSendFailed(RuntimeError):
    """The provider was asked and did not accept the message."""


def from_address() -> str:
    """
    The sender, which must be on a domain verified with Resend.

    Configurable because the old hardcoded `alerts@vaulto.in` fails with a 403
    on every send until that domain is verified, and the error is invisible
    from outside the logs.
    """
    return (os.getenv("ALERT_FROM_EMAIL") or "").strip() or FALLBACK_FROM


def email_configured() -> bool:
    """Whether a send would be attempted at all."""
    return bool((os.getenv("RESEND_API_KEY") or "").strip())


async def send_email(
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
) -> None:
    """
    Send one email. Returns None on success, raises on every failure.

    Raises:
        EmailNotConfigured: no RESEND_API_KEY — nothing was attempted.
        EmailSendFailed:    Resend refused it, or was unreachable.
    """
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise EmailNotConfigured(
            "RESEND_API_KEY is not set — no email was attempted. "
            "Create a key at https://resend.com/api-keys."
        )

    payload = {
        "from": from_address(),
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise EmailSendFailed(f"could not reach Resend: {exc}") from exc

    if response.status_code >= 400:
        # Resend explains itself in the body, and the explanation is usually
        # actionable ("the X domain is not verified"). Losing it to a bare
        # status code is what made this failure mode so hard to see.
        detail = _explain(response)
        raise EmailSendFailed(
            f"Resend rejected the message (HTTP {response.status_code}): {detail}"
        )

    logger.info("Email sent to %s — %s", to, subject)


def _explain(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)[:300]
    return str(body)[:300]
