"""
Verifying Supabase access tokens — and refusing the ones that only look valid.

The failures that matter here are the quiet ones. A token signed by a
*different* Supabase project, or the anon key itself (which is also a JWT),
both carry a correct signature over a well-formed payload. Nothing about
decoding them fails; only checking the issuer and the audience does.
"""

import datetime

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import auth
import supabase_client

SECRET = "super-secret-jwt-token-with-at-least-32-characters"
PROJECT = "https://abcdefgh.supabase.co"
USER_ID = "3f0c9a7e-2b41-4d8e-9c1a-5f6b7c8d9e01"


def make_token(secret=SECRET, **overrides):
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": USER_ID,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "email": "student@example.com",
        "user_metadata": {"full_name": "Alex Johnson"},
        "iat": now,
        "exp": now + datetime.timedelta(hours=1),
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


def creds(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture(autouse=True)
def project_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)


class TestTokenVerification:
    def test_a_valid_token_yields_the_identity(self):
        user = auth.verify_supabase_token(creds(make_token()))

        assert user["user_id"] == USER_ID
        assert user["email"] == "student@example.com"
        assert user["full_name"] == "Alex Johnson"

    def test_a_trailing_slash_on_the_project_url_still_matches(self, monkeypatch):
        """The dashboard's copy button is the usual source of one."""
        monkeypatch.setenv("SUPABASE_URL", PROJECT + "/")

        assert auth.verify_supabase_token(creds(make_token()))["user_id"] == USER_ID

    def test_another_projects_token_is_rejected(self):
        """
        Correctly signed, correctly shaped, and issued by someone else. Only
        pinning the issuer catches this.
        """
        token = make_token(iss="https://someoneelse.supabase.co/auth/v1")

        with pytest.raises(HTTPException) as excinfo:
            auth.verify_supabase_token(creds(token))
        assert excinfo.value.status_code == 401

    def test_the_anon_key_does_not_authenticate_anyone(self):
        """
        The publishable key shipped to every browser IS a JWT signed with the
        project's secret. Its audience is not `authenticated`.
        """
        token = make_token(aud="anon", role="anon", sub="anon")

        with pytest.raises(HTTPException) as excinfo:
            auth.verify_supabase_token(creds(token))
        assert excinfo.value.status_code == 401

    def test_a_token_signed_with_the_wrong_secret_is_rejected(self):
        with pytest.raises(HTTPException) as excinfo:
            auth.verify_supabase_token(creds(make_token(secret="not-the-secret")))
        assert excinfo.value.status_code == 401

    def test_an_expired_token_is_rejected(self):
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        token = make_token(iat=past, exp=past + datetime.timedelta(minutes=1))

        with pytest.raises(HTTPException) as excinfo:
            auth.verify_supabase_token(creds(token))
        assert excinfo.value.status_code == 401

    def test_a_token_issued_a_moment_ahead_of_our_clock_is_accepted(self):
        """
        Supabase's clock and ours are not the same clock. Without leeway a
        freshly-minted token fails with "not yet valid", intermittently.
        """
        ahead = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=20)
        token = make_token(iat=ahead, exp=ahead + datetime.timedelta(hours=1))

        assert auth.verify_supabase_token(creds(token))["user_id"] == USER_ID

    def test_a_token_with_no_subject_is_rejected(self):
        with pytest.raises(HTTPException):
            auth.verify_supabase_token(creds(make_token(sub=None)))

    def test_an_hs256_token_without_a_configured_secret_fails_loudly(self, monkeypatch):
        """A 500, not a 401: the deployment is misconfigured, not the caller."""
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)

        with pytest.raises(HTTPException) as excinfo:
            auth.verify_supabase_token(creds(make_token()))
        assert excinfo.value.status_code == 500


class TestAdminGate:
    def test_an_empty_allowlist_admits_nobody(self):
        """An unset ADMIN_USER_IDS must not mean "everyone is an admin"."""
        with pytest.raises(HTTPException) as excinfo:
            auth.verify_admin_token(creds(make_token()))
        assert excinfo.value.status_code == 403

    def test_a_listed_id_is_admitted(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", f" other-id , {USER_ID} ")

        assert auth.verify_admin_token(creds(make_token()))["user_id"] == USER_ID

    def test_an_unlisted_id_is_refused(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "some-other-uuid")

        with pytest.raises(HTTPException) as excinfo:
            auth.verify_admin_token(creds(make_token()))
        assert excinfo.value.status_code == 403


class TestJwksDiscovery:
    def test_the_jwks_url_is_derived_from_the_project(self):
        assert auth.jwks_url() == f"{PROJECT}/auth/v1/.well-known/jwks.json"

    def test_an_explicit_jwks_url_wins(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.test/keys")

        assert auth.jwks_url() == "https://example.test/keys"


class TestClaimExtraction:
    def test_a_google_identity_supplies_the_address_when_the_top_level_is_empty(self):
        payload = {
            "email": "",
            "identities": [
                {"provider": "google", "identity_data": {"email": "g@example.com"}}
            ],
        }

        assert supabase_client._primary_email(payload) == "g@example.com"

    def test_no_address_anywhere_is_none_not_an_empty_string(self):
        assert supabase_client._primary_email({"email": "", "identities": []}) is None
