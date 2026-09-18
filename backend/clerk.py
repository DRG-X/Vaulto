"""
clerk.py — reading from Clerk the things its session token does not carry.

The problem this solves
-----------------------
`auth.py` built every user record with `email=payload.get("email")`. Clerk's
DEFAULT session token carries `azp, exp, iat, iss, nbf, sid, sub, v` — and no
email. That claim only exists if someone has added it to a custom JWT template
in the Clerk dashboard, which this project never did.

So `user.email` was NULL for every account, and the alert notifier's
`if alert.notify_email and user.email:` was never true. Rate alerts fired,
were marked as triggered, and mailed nobody. Nothing logged an error, because
from the code's point of view nothing had gone wrong.

Reading it from the Backend API is the fix that does not depend on dashboard
configuration being right. `CLERK_SECRET_KEY` is already required by this
deployment, so there is no new secret to provision.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"
TIMEOUT = 10


def secret_key() -> str:
    return (os.getenv("CLERK_SECRET_KEY") or "").strip()


async def fetch_primary_email(clerk_user_id: str) -> Optional[str]:
    """
    The user's primary email address from Clerk, or None.

    Returns None rather than raising: a missing address is a reason not to
    send, not a reason to take down the alert run. The caller logs it.
    """
    key = secret_key()
    if not key:
        logger.warning(
            "CLERK_SECRET_KEY is not set — cannot look up an email address for %s",
            clerk_user_id,
        )
        return None

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{CLERK_API_BASE}/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Clerk lookup failed for %s: %s", clerk_user_id, exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Clerk lookup for %s returned HTTP %s", clerk_user_id, response.status_code
        )
        return None

    try:
        return _primary_email(response.json())
    except ValueError:
        logger.warning("Clerk lookup for %s returned a non-JSON body", clerk_user_id)
        return None


def _primary_email(payload: dict) -> Optional[str]:
    """
    Pick the primary address out of a Clerk user object.

    Clerk returns every address the account has verified, in no guaranteed
    order, and names the primary one by id. Taking the first entry would mail
    an old address the user may no longer read.
    """
    addresses = payload.get("email_addresses") or []
    if not addresses:
        return None

    primary_id = payload.get("primary_email_address_id")
    if primary_id:
        for entry in addresses:
            if entry.get("id") == primary_id:
                address = (entry.get("email_address") or "").strip()
                if address:
                    return address

    # No primary flagged — fall back to the first address that exists at all.
    for entry in addresses:
        address = (entry.get("email_address") or "").strip()
        if address:
            return address
    return None


def email_from_claims(payload: dict) -> Optional[str]:
    """
    An email claim from the session token, if a JWT template supplies one.

    Free and instant when it is there, so it is tried before the API call.
    Clerk templates spell it several ways depending on how they were built.
    """
    for claim in ("email", "email_address", "primary_email_address"):
        value = payload.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
