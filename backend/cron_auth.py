"""
cron_auth.py — the shared secret that guards /internal/check-alerts.

Why a shared secret and not Google IAM
--------------------------------------
Cloud Run can require a Google-signed OIDC token on every request, which is the
stronger control. The caller here is Supabase Cron: a `pg_cron` job issuing an
HTTP request through `pg_net`, from inside Postgres. It has no Google service
account and no way to mint an OIDC token, so an IAM-protected service cannot be
reached from it at all.

So the service is deployed `--allow-unauthenticated` and this endpoint carries
its own door: a long random secret that only Supabase and Cloud Run know. On the
Supabase side it lives in Vault, not in the job's SQL body; on the Cloud Run side
it is a Secret Manager secret exposed as `CRON_SECRET`.

What this is NOT
----------------
This is not user authentication and grants nothing but the right to start an
alert run. It is deliberately separate from `auth.py`, which verifies Supabase
*user* tokens — a user token must never open this endpoint, and this secret must
never stand in for a user.
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

#: Shorter than this and the secret is guessable at Cloud Run's request rates.
#: `openssl rand -hex 32` produces 64 characters and is what the docs tell you
#: to run.
MIN_SECRET_LENGTH = 32


def cron_secret() -> str:
    return (os.getenv("CRON_SECRET") or "").strip()


def _presented(authorization: str | None, x_cron_secret: str | None) -> str:
    """
    The secret the caller offered, from either header it may arrive in.

    `Authorization: Bearer …` is what the Supabase Cron job sends. `X-Cron-Secret`
    exists because some proxies and dashboards strip or rewrite Authorization,
    and losing a scheduled job to that is a bad way to find out.
    """
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return (x_cron_secret or "").strip()


def verify_cron_secret(
    request: Request,
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
) -> None:
    """
    FastAPI dependency: let the request through only if it carries the secret.

    Fails CLOSED. With `CRON_SECRET` unset nothing is accepted, so a deployment
    that forgot it cannot be triggered by anyone — including the operator, which
    is the point: a 503 saying so is how you find out, rather than discovering
    months later that alerts were open to the internet.
    """
    expected = cron_secret()
    if not expected:
        logger.error(
            "CRON_SECRET is not set — /internal/check-alerts is refusing every "
            "request. Set it on the Cloud Run service and in Supabase Vault; see "
            "ENVIRONMENT.md."
        )
        raise HTTPException(
            status_code=503,
            detail="This endpoint is not configured. CRON_SECRET is unset.",
        )

    if len(expected) < MIN_SECRET_LENGTH:
        # Loud, but not fatal: refusing to run would turn a weak secret into no
        # alerts at all, which is the worse failure.
        logger.warning(
            "CRON_SECRET is only %d characters. Use at least %d — `openssl rand -hex 32`.",
            len(expected), MIN_SECRET_LENGTH,
        )

    presented = _presented(authorization, x_cron_secret)

    # compare_digest, not ==, so the comparison does not return early on the
    # first wrong byte and leak the secret one character at a time. Both sides
    # are encoded first because compare_digest rejects non-ASCII str input.
    if not presented or not hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        # The caller is a machine, so there is nothing to explain to it. The
        # client IP is logged because a stream of these is worth noticing, and
        # the presented value is NOT logged — near-miss secrets do not belong in
        # a log aggregator.
        logger.warning(
            "Rejected /internal request with a missing or incorrect secret (from %s)",
            request.headers.get("X-Forwarded-For") or
            (request.client.host if request.client else "unknown"),
        )
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret.")
