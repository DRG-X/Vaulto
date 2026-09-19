"""
supabase_client.py — reading from Supabase the things a token cannot tell us.

What this is for
----------------
A Supabase access token carries `email` as a claim, so in the common case the
address is already in hand by the time `auth.py` is done with the token. Two
cases are not the common case:

  * a user whose email was changed (or first confirmed) after the token in a
    stored row was minted, and
  * a row created before the address was ever captured — every account Vaulto
    migrated over from Clerk, whose session JWT carried no email claim at all
    and left `users.email` NULL.

The alert notifier reads `user.email`. When it is missing, the address is not
gone — it lives in `auth.users`, which only the service-role key may read.
This module is that lookup, and nothing else.

`SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security entirely. It is a
server-side secret: it must never be sent to a browser, and it is never the
key the frontend is given (that is the anon/publishable key).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10


def project_url() -> str:
    """
    The project's base URL, e.g. https://abcdefgh.supabase.co — no trailing slash.

    A trailing slash is the most common way this is pasted out of the Supabase
    dashboard, and it turns every derived URL into a double-slashed 404.
    """
    return (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")


def service_role_key() -> str:
    return (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def auth_base() -> str:
    base = project_url()
    return f"{base}/auth/v1" if base else ""


async def fetch_primary_email(user_id: str) -> Optional[str]:
    """
    The user's email address from Supabase Auth, or None.

    Returns None rather than raising: a missing address is a reason not to
    send, not a reason to take down the alert run. The caller logs it.
    """
    base = auth_base()
    key = service_role_key()
    if not base or not key:
        logger.warning(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not both set — cannot "
            "look up an email address for %s",
            user_id,
        )
        return None

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{base}/admin/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {key}",
                    # GoTrue requires apikey alongside the bearer token; without
                    # it the request is rejected before the token is looked at.
                    "apikey": key,
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Supabase user lookup failed for %s: %s", user_id, exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Supabase user lookup for %s returned HTTP %s",
            user_id, response.status_code,
        )
        return None

    try:
        return _primary_email(response.json())
    except ValueError:
        logger.warning("Supabase user lookup for %s returned a non-JSON body", user_id)
        return None


def _primary_email(payload: dict) -> Optional[str]:
    """
    Pick the address out of a GoTrue user object.

    `email` is the account's own address. `identities` holds one entry per
    linked provider (email, google, …) and is the fallback for an account
    created purely through OAuth, where GoTrue has occasionally left the
    top-level field empty.
    """
    address = (payload.get("email") or "").strip()
    if address:
        return address

    for identity in payload.get("identities") or []:
        data = identity.get("identity_data") or {}
        address = (data.get("email") or "").strip()
        if address:
            return address
    return None


def email_from_claims(payload: dict) -> Optional[str]:
    """
    The email claim from the access token, when it is there.

    Free and instant, so it is tried before the API call above. Supabase puts
    it at the top level; a custom access-token hook may instead leave it in
    `user_metadata`, which is why both are checked.
    """
    value = payload.get("email")
    if isinstance(value, str) and value.strip():
        return value.strip()

    metadata = payload.get("user_metadata")
    if isinstance(metadata, dict):
        value = metadata.get("email")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def full_name_from_claims(payload: dict) -> Optional[str]:
    """
    A display name from the token, if the sign-up flow supplied one.

    Email sign-up writes whatever the form sent into `user_metadata`; Google
    sign-in writes `full_name` and `name`. Neither is guaranteed.
    """
    metadata = payload.get("user_metadata")
    if not isinstance(metadata, dict):
        return None
    for claim in ("full_name", "name", "display_name"):
        value = metadata.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
