"""
Sign-in and onboarding, end to end at the API boundary.

These are the two calls every single user makes before they see anything, so
their failure modes are the ones nobody can route around: a sync that 403s
because the client had not hydrated its user object yet, two syncs racing each
other into a unique-constraint 500, or an onboarding write that stores a
corridor whose legs are the same currency and turns every "compare now" link
into an error page.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import models
from auth import verify_clerk_token
from database import Base, get_db


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,   # one shared in-memory DB across sessions
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[verify_clerk_token] = lambda: {
        "clerk_user_id": "user_abc",
        "email": "token@example.com",
    }
    c = TestClient(main.app)
    c.session_factory = TestingSession
    yield c
    main.app.dependency_overrides.clear()


class TestSync:
    def test_first_sync_creates_an_un_onboarded_user(self, client):
        r = client.post("/api/users/sync", json={
            "clerk_id": "user_abc", "email": "a@b.com", "full_name": "Ada L",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["clerk_user_id"] == "user_abc"
        assert body["is_onboarded"] is False
        assert body["full_name"] == "Ada L"

    def test_sync_is_idempotent(self, client):
        first = client.post("/api/users/sync", json={"clerk_id": "user_abc", "email": "a@b.com"})
        second = client.post("/api/users/sync", json={"clerk_id": "user_abc", "email": "a@b.com"})
        assert first.json()["id"] == second.json()["id"]

    def test_sync_without_a_clerk_id_uses_the_token(self, client):
        """
        The regression: post-auth fires before Clerk hydrates `user`, sends
        `clerk_id: ""`, and the user's first screen 403s.
        """
        r = client.post("/api/users/sync", json={"clerk_id": "", "email": ""})
        assert r.status_code == 200
        assert r.json()["clerk_user_id"] == "user_abc"

    def test_sync_still_refuses_someone_elses_account(self, client):
        r = client.post("/api/users/sync", json={"clerk_id": "user_someone_else", "email": "x@y.com"})
        assert r.status_code == 403

    def test_a_losing_insert_race_adopts_the_winner(self, client):
        """
        post-auth and the dashboard both sync on first load. The loser used to
        raise IntegrityError and surface as a 500 on the very first screen.
        """
        other = client.session_factory()
        other.add(models.User(clerk_user_id="user_abc", email="race@b.com", is_onboarded=False))
        other.commit()
        row_id = other.query(models.User).filter_by(clerk_user_id="user_abc").one().id
        other.close()

        r = client.post("/api/users/sync", json={"clerk_id": "user_abc", "email": "a@b.com"})
        assert r.status_code == 200
        assert r.json()["id"] == row_id

    def test_sync_refreshes_a_changed_name(self, client):
        client.post("/api/users/sync", json={"clerk_id": "user_abc", "full_name": "Ada L"})
        r = client.post("/api/users/sync", json={"clerk_id": "user_abc", "full_name": "Ada Lovelace"})
        assert r.json()["full_name"] == "Ada Lovelace"


class TestStatus:
    def test_unknown_user_is_neither_existing_nor_onboarded(self, client):
        r = client.get("/user/status")
        assert r.json() == {"exists": False, "is_onboarded": False}

    def test_status_flips_after_onboarding(self, client):
        client.post("/api/users/sync", json={"clerk_id": "user_abc"})
        assert client.get("/user/status").json() == {"exists": True, "is_onboarded": False}

        client.post("/api/onboarding/complete", json={
            "country": "GB", "university": "UCL",
            "home_currency": "INR", "corridor_from": "GBP", "corridor_to": "INR",
        })
        assert client.get("/user/status").json() == {"exists": True, "is_onboarded": True}


class TestOnboarding:
    def test_completing_onboarding_stores_the_corridor(self, client):
        client.post("/api/users/sync", json={"clerk_id": "user_abc"})
        r = client.post("/api/onboarding/complete", json={
            "country": "gb", "university": " University College London ",
            "whatsapp_number": "+44 7700 900-123",
            "home_currency": "inr", "corridor_from": "gbp", "corridor_to": "inr",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["is_onboarded"] is True
        assert body["country"] == "GB"
        assert (body["corridor_from"], body["corridor_to"]) == ("GBP", "INR")
        assert body["whatsapp_number"] == "+447700900123"
        assert body["university"] == "University College London"

    def test_onboarding_works_when_sync_never_ran(self, client):
        """No 404 dead-end after the user has filled in the whole wizard."""
        r = client.post("/api/onboarding/complete", json={
            "country": "AU", "corridor_from": "AUD", "corridor_to": "INR",
        })
        assert r.status_code == 200
        assert r.json()["is_onboarded"] is True

    def test_a_corridor_that_goes_nowhere_is_refused(self, client):
        """
        The regression: onboarding derived BOTH legs from the one country the
        user picked, so everyone was stored as INR -> INR and every compare
        link off the dashboard 422'd.
        """
        r = client.post("/api/onboarding/complete", json={
            "country": "IN", "corridor_from": "INR", "corridor_to": "INR",
        })
        assert r.status_code == 422

    def test_a_missing_country_is_refused(self, client):
        assert client.post("/api/onboarding/complete", json={"country": ""}).status_code == 422

    def test_an_unusable_phone_number_is_refused(self, client):
        r = client.post("/api/onboarding/complete", json={
            "country": "GB", "whatsapp_number": "12345",
            "corridor_from": "GBP", "corridor_to": "INR",
        })
        assert r.status_code == 422


class TestSettingsUpdate:
    def _onboard(self, client):
        client.post("/api/onboarding/complete", json={
            "country": "GB", "corridor_from": "GBP", "corridor_to": "INR",
        })

    def test_partial_update_normalises(self, client):
        self._onboard(client)
        r = client.patch("/api/users/me", json={"corridor_from": "aud", "whatsapp_number": "447700900123"})
        assert r.status_code == 200
        assert r.json()["corridor_from"] == "AUD"
        assert r.json()["whatsapp_number"] == "+447700900123"

    def test_one_leg_cannot_be_changed_to_match_the_other(self, client):
        self._onboard(client)
        r = client.patch("/api/users/me", json={"corridor_from": "INR"})
        assert r.status_code == 422
        assert client.get("/api/users/me").json()["corridor_from"] == "GBP"


class TestLegacyProfile:
    def test_reposting_a_profile_saves_the_change(self, client):
        client.post("/user/profile", json={"country": "GB", "university": "UCL"})
        r = client.post("/user/profile", json={"country": "AU", "university": "RMIT"})
        assert r.status_code == 201
        assert r.json()["country"] == "AU"
        assert r.json()["is_new_user"] is False
