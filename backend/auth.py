"""
auth.py — verifying Supabase Auth access tokens.

What a Supabase access token looks like
---------------------------------------
GoTrue issues a JWT whose `sub` is the user's UUID in `auth.users`, with
`aud: "authenticated"`, `iss: "<project>/auth/v1"`, and — unlike the Clerk
session token this replaced — an `email` claim as standard. That one
difference removes a whole class of bug: the address needed to deliver a rate
alert arrives with the request instead of having to be fetched afterwards.

Two signing schemes, both supported
-----------------------------------
Supabase is moving projects from a single shared HS256 secret to asymmetric
JWT signing keys published as a JWKS. Which one a project uses depends on
when it was created and whether its keys have been rotated, and a project can
hold both during a rotation.

Rather than make the deployment declare it, the token's own `alg` header
decides: HS256 is verified against `SUPABASE_JWT_SECRET`, anything asymmetric
against the project's JWKS. A rotation therefore needs no redeploy — tokens
signed the new way start verifying the moment they appear.
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWKClient

import supabase_client

logger = logging.getLogger(__name__)

security = HTTPBearer()

# Allow up to 60 s of clock skew between Supabase's servers and this machine,
# which otherwise rejects freshly-minted tokens with "not yet valid (iat)".
CLOCK_SKEW_LEEWAY = datetime.timedelta(seconds=60)

#: Every user token GoTrue issues carries this audience. Anon tokens (the
#: publishable key itself is a JWT) carry "anon" and must NOT authenticate a
#: request — verifying the audience is what keeps a public key out of here.
DEFAULT_AUDIENCE = "authenticated"

ASYMMETRIC_ALGORITHMS = ["RS256", "RS512", "ES256", "ES512", "EdDSA"]

_jwks_client: Optional[PyJWKClient] = None


def jwks_url() -> str:
    """Where the project publishes its public signing keys."""
    explicit = (os.getenv("SUPABASE_JWKS_URL") or "").strip()
    if explicit:
        return explicit
    base = supabase_client.auth_base()
    return f"{base}/.well-known/jwks.json" if base else ""


def jwt_secret() -> str:
    """The legacy shared HS256 secret, for projects not yet on asymmetric keys."""
    return (os.getenv("SUPABASE_JWT_SECRET") or "").strip()


def expected_audience() -> str:
    return (os.getenv("SUPABASE_JWT_AUD") or "").strip() or DEFAULT_AUDIENCE


def expected_issuer() -> Optional[str]:
    """
    The issuer to pin to, or None when SUPABASE_URL is unset (local dev).

    Pinning matters: without it a correctly-signed token from a *different*
    Supabase project would be accepted, since every project's tokens share the
    same shape and audience.
    """
    base = supabase_client.auth_base()
    return base or None


def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    url = jwks_url()
    if not url:
        return None
    # Rebuilt only when the URL changes, so the key set is fetched once and
    # cached rather than on every request.
    if _jwks_client is None or _jwks_client.uri != url:
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks_client


def _decode(token: str) -> dict:
    """Verify the signature and the standard claims, or raise PyJWTError."""
    header = jwt.get_unverified_header(token)
    algorithm = (header.get("alg") or "").upper()

    options = {"require": ["exp", "sub"]}
    common = {
        "leeway": CLOCK_SKEW_LEEWAY,
        "audience": expected_audience(),
        "options": options,
    }
    issuer = expected_issuer()
    if issuer:
        common["issuer"] = issuer

    if algorithm.startswith("HS"):
        secret = jwt_secret()
        if not secret:
            raise HTTPException(
                status_code=500,
                detail=(
                    "This token is signed with the legacy shared secret, but "
                    "SUPABASE_JWT_SECRET is not configured."
                ),
            )
        return jwt.decode(token, secret, algorithms=["HS256"], **common)

    client = _get_jwks_client()
    if not client:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL (or SUPABASE_JWKS_URL) is not configured.",
        )
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token, signing_key.key, algorithms=ASYMMETRIC_ALGORITHMS, **common
    )


def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    FastAPI dependency: the authenticated user behind this request.

    Returns the identity the rest of the app works in: the Supabase user UUID,
    and the email and display name the token happens to carry.
    """
    try:
        payload = _decode(credentials.credentials)
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")
    except Exception as exc:  # JWKS fetch failures surface here
        logger.warning("Token verification could not complete: %s", exc)
        raise HTTPException(status_code=401, detail="Authentication failed")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid JWT: missing 'sub' claim.")

    # A token minted for the anonymous role is a valid signature over a
    # non-user. `aud` is verified above, but `role` is what GoTrue actually
    # switches on, and a custom claims hook can move them apart.
    role = payload.get("role")
    if role and role not in ("authenticated", expected_audience()):
        raise HTTPException(status_code=401, detail="Not an authenticated user token.")

    return {
        "user_id": user_id,
        "email": supabase_client.email_from_claims(payload),
        "full_name": supabase_client.full_name_from_claims(payload),
    }


def admin_user_ids() -> list[str]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    user = verify_supabase_token(credentials)
    allowed = admin_user_ids()
    if not allowed or user["user_id"] not in allowed:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
