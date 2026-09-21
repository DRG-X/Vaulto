"""
The cron-triggered alert endpoint, and the door in front of it.

This endpoint replaced an in-process APScheduler job, because Cloud Run scales
to zero and a process that does not exist cannot tick. That swap moves the
trigger onto the public internet, so the tests that matter here are the ones
about who is allowed to pull it, and about what happens when two ticks overlap —
a duplicated run means a user gets the same alert email twice, since an alert is
only paused once its delivery is confirmed.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import cron_auth
import main

SECRET = "b8f0c1d2e3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0"
URL = "/internal/check-alerts"


@pytest.fixture()
def client(monkeypatch):
    """
    A client whose alert check is a no-op that records that it was called.

    The real `check_alerts` reaches for a database and 28 provider APIs; what is
    under test is the endpoint around it. TestClient is used WITHOUT its context
    manager on purpose, so the app's lifespan (migrations, Redis, model import)
    never runs.
    """
    monkeypatch.setenv("CRON_SECRET", SECRET)

    calls = []

    async def fake_check_alerts():
        calls.append("ran")

    monkeypatch.setattr(main, "check_alerts", fake_check_alerts)
    # Redis is not configured in tests, so the cross-instance lock is a no-op
    # that returns True. Being explicit keeps this test from depending on that.
    async def always_free(name, ttl):
        return True

    async def noop_release(name):
        return None

    monkeypatch.setattr(main, "try_acquire_lock", always_free)
    monkeypatch.setattr(main, "release_lock", noop_release)

    c = TestClient(main.app)
    c.calls = calls
    return c


class TestTheDoor:
    def test_no_credentials_is_refused(self, client):
        r = client.post(URL)
        assert r.status_code == 401
        assert client.calls == []

    def test_a_wrong_secret_is_refused(self, client):
        r = client.post(URL, headers={"Authorization": f"Bearer {'a' * len(SECRET)}"})
        assert r.status_code == 401
        assert client.calls == []

    def test_a_prefix_of_the_secret_is_refused(self, client):
        """Guards against a comparison that stops at the first differing byte."""
        r = client.post(URL, headers={"Authorization": f"Bearer {SECRET[:-1]}"})
        assert r.status_code == 401
        assert client.calls == []

    def test_a_user_token_does_not_open_this_door(self, client):
        """
        A Supabase access token is not a cron credential.

        The two auth paths are deliberately separate: any signed-in user could
        otherwise start an alert run at will.
        """
        r = client.post(URL, headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x"})
        assert r.status_code == 401
        assert client.calls == []

    def test_the_bearer_header_works(self, client):
        r = client.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        assert r.status_code == 200
        assert client.calls == ["ran"]

    def test_the_fallback_header_works(self, client):
        """For proxies that rewrite or strip Authorization."""
        r = client.post(URL, headers={"X-Cron-Secret": SECRET})
        assert r.status_code == 200
        assert client.calls == ["ran"]

    def test_the_scheme_must_be_bearer(self, client):
        r = client.post(URL, headers={"Authorization": f"Basic {SECRET}"})
        assert r.status_code == 401

    def test_an_unconfigured_deployment_accepts_nobody(self, client, monkeypatch):
        """
        Fails CLOSED, and says why.

        With no secret set, an `==` against "" would let a request with no
        credentials straight through to the alert runner.
        """
        monkeypatch.delenv("CRON_SECRET", raising=False)
        assert client.post(URL).status_code == 503
        assert client.post(URL, headers={"Authorization": "Bearer "}).status_code == 503
        assert client.calls == []

    def test_a_blank_secret_counts_as_unconfigured(self, client, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "   ")
        assert client.post(URL).status_code == 503
        assert client.calls == []

    def test_get_is_not_allowed(self, client):
        """The trigger is a POST; a crawler following a link must not start a run."""
        assert client.get(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 405
        assert client.calls == []


class TestTheRun:
    def test_a_successful_pass_reports_its_duration(self, client):
        body = client.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).json()
        assert body["status"] == "completed"
        assert isinstance(body["duration_seconds"], (int, float))

    def test_each_tick_runs_the_check_once(self, client):
        for _ in range(3):
            assert client.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 200
        assert client.calls == ["ran", "ran", "ran"]

    def test_a_failing_check_is_a_500_not_a_silent_success(self, client, monkeypatch):
        """
        A tick that blew up must not look like a tick that worked — Supabase
        records the status in cron.job_run_details, and that is the only place
        anyone is going to notice.
        """
        async def explodes():
            raise RuntimeError("provider fan-out died")

        monkeypatch.setattr(main, "check_alerts", explodes)
        assert client.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 500

    def test_the_lock_is_released_after_a_failure(self, client, monkeypatch):
        """Otherwise one bad run wedges the endpoint until the TTL expires."""
        released = []

        async def explodes():
            raise RuntimeError("boom")

        async def record_release(name):
            released.append(name)

        monkeypatch.setattr(main, "check_alerts", explodes)
        monkeypatch.setattr(main, "release_lock", record_release)
        client.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        assert released == [main.ALERT_RUN_LOCK]
        assert not main._alert_run_lock.locked()

    def test_another_instance_holding_the_lock_skips_the_tick(self, client, monkeypatch):
        async def taken(name, ttl):
            return False

        monkeypatch.setattr(main, "try_acquire_lock", taken)
        r = client.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        assert r.status_code == 409
        assert client.calls == []

    def test_the_lock_is_not_left_held_by_a_skipped_tick(self, client, monkeypatch):
        async def taken(name, ttl):
            return False

        monkeypatch.setattr(main, "try_acquire_lock", taken)
        client.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        assert not main._alert_run_lock.locked()
        # And the next tick, once the other instance is done, still runs.
        monkeypatch.setattr(main, "try_acquire_lock", lambda name, ttl: _true())
        assert client.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 200
        assert client.calls == ["ran"]


async def _true():
    return True


class TestOverlappingTicks:
    async def test_a_second_tick_on_this_instance_is_refused_not_queued(self, monkeypatch):
        """
        Two overlapping ticks must not both read the same active alerts.

        Queueing would be worse than skipping: the second run would start the
        moment the first finished and re-check alerts that were just checked.
        """
        monkeypatch.setenv("CRON_SECRET", SECRET)
        started = asyncio.Event()
        release = asyncio.Event()
        runs = []

        async def slow_check():
            runs.append("start")
            started.set()
            await release.wait()

        monkeypatch.setattr(main, "check_alerts", slow_check)

        async def always_free(name, ttl):
            return True

        async def noop_release(name):
            return None

        monkeypatch.setattr(main, "try_acquire_lock", always_free)
        monkeypatch.setattr(main, "release_lock", noop_release)

        # Drive the handler directly: TestClient is synchronous and cannot hold
        # one request open while issuing another.
        first = asyncio.create_task(main.run_alert_check())
        await started.wait()

        with pytest.raises(Exception) as excinfo:
            await main.run_alert_check()
        assert getattr(excinfo.value, "status_code", None) == 409

        release.set()
        await first
        assert runs == ["start"]
        assert not main._alert_run_lock.locked()


class TestSecretParsing:
    @pytest.mark.parametrize("header,expected", [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER abc", "abc"),
        ("Bearer   abc  ", "abc"),
        ("Basic abc", ""),
        ("abc", ""),
        ("Bearer", ""),
        ("Bearer ", ""),
    ])
    def test_bearer_is_parsed_case_insensitively(self, header, expected):
        assert cron_auth._presented(header, None) == expected

    def test_authorization_wins_over_the_fallback(self):
        assert cron_auth._presented("Bearer one", "two") == "one"

    def test_the_fallback_is_used_when_authorization_is_unusable(self):
        """A proxy that replaces Authorization must not lock the caller out."""
        assert cron_auth._presented("Basic junk", "two") == "two"
        assert cron_auth._presented(None, "two") == "two"


class TestEndToEndThroughTheEndpoint:
    """
    One HTTP tick, the real `check_alerts`, a real database, a real delivered
    alert.

    Everything between the request and the email is the untouched alert logic.
    What this pins is that moving the trigger from APScheduler to an HTTP request
    did not change the outcome: an alert whose target is met is still delivered
    and still paused, and one whose target is not met is still left alone.
    """

    @pytest.fixture()
    def db(self, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import scheduler as scheduler_module
        from database import Base

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        # check_alerts opens its own session; point that at this database.
        monkeypatch.setattr(scheduler_module, "SessionLocal", Session)
        return Session

    @pytest.fixture()
    def live(self, monkeypatch, db):
        """The endpoint wired to the real checker, with the outside world stubbed."""
        import notifications
        import scheduler as scheduler_module

        monkeypatch.setenv("CRON_SECRET", SECRET)
        monkeypatch.setattr(main, "check_alerts", scheduler_module.check_alerts)

        async def always_free(name, ttl):
            return True

        async def noop_release(name):
            return None

        monkeypatch.setattr(main, "try_acquire_lock", always_free)
        monkeypatch.setattr(main, "release_lock", noop_release)

        # No cache, so check_alerts goes to fetch_pools — which is stubbed with
        # one Wise bank quote at a rate of 56.
        async def no_cache(*a, **k):
            return None

        async def no_write(*a, **k):
            return None

        monkeypatch.setattr(scheduler_module, "get_cached_rates", no_cache)
        monkeypatch.setattr(scheduler_module, "set_cached_rates", no_write)

        # One Wise bank-deposit option at a rate of 56. Built as a namespace for
        # the same reason tests/test_alerts.py does: `_quote_for_alert` and
        # `check_alerts` read three attributes off a quote, and a real
        # ProviderQuote would pull the whole normalization pipeline in with it.
        async def fake_fetch_pools(amount, from_cur, to_cur):
            quote = SimpleNamespace(
                provider="Wise", exchange_rate=56.0, pay_out_method="BANK_DEPOSIT",
            )
            return SimpleNamespace(
                pools={"Wise": [quote]},
                to_dict=lambda: {"pools": {}},   # only ever handed to the stubbed cache
            )

        monkeypatch.setattr(scheduler_module, "fetch_pools", fake_fetch_pools)

        sent = []

        async def capture_email(to, subject, text, html=None):
            sent.append({"to": to, "subject": subject, "text": text})

        monkeypatch.setattr(notifications, "send_email", capture_email)

        c = TestClient(main.app)
        c.sent = sent
        return c

    def _seed(self, db, target_rate, email="student@example.com"):
        import models

        s = db()
        user = models.User(
            supabase_user_id="3f0c9a7e-2b41-4d8e-9c1a-5f6b7c8d9e01",
            email=email,
            is_onboarded=True,
        )
        s.add(user)
        s.commit()
        alert = models.RateAlert(
            supabase_user_id=user.supabase_user_id,
            from_currency="AUD",
            to_currency="INR",
            amount=1000.0,
            target_rate=target_rate,
            notify_email=True,
            is_active=True,
        )
        s.add(alert)
        s.commit()
        alert_id = alert.id
        s.close()
        return alert_id

    def _alert(self, db, alert_id):
        import models

        s = db()
        row = s.query(models.RateAlert).filter(models.RateAlert.id == alert_id).one()
        state = (row.is_active, row.last_triggered)
        s.close()
        return state

    def test_a_met_target_is_delivered_and_paused(self, live, db):
        alert_id = self._seed(db, target_rate=55.0)   # market is at 56

        r = live.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        assert r.status_code == 200

        assert len(live.sent) == 1, "the user should have been emailed exactly once"
        assert live.sent[0]["to"] == "student@example.com"
        assert "56.0000" in live.sent[0]["text"]

        is_active, last_triggered = self._alert(db, alert_id)
        assert is_active is False, "a delivered alert is paused"
        assert last_triggered is not None

    def test_an_unmet_target_is_left_alone(self, live, db):
        alert_id = self._seed(db, target_rate=60.0)   # market is at 56

        assert live.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 200

        assert live.sent == []
        is_active, last_triggered = self._alert(db, alert_id)
        assert is_active is True, "an alert that did not hit stays armed"
        assert last_triggered is None

    def test_a_paused_alert_is_not_re_delivered_by_the_next_tick(self, live, db):
        """The second tick 15 minutes later must not mail the same alert again."""
        self._seed(db, target_rate=55.0)

        live.post(URL, headers={"Authorization": f"Bearer {SECRET}"})
        live.post(URL, headers={"Authorization": f"Bearer {SECRET}"})

        assert len(live.sent) == 1

    def test_an_undeliverable_alert_keeps_its_watch(self, live, db, monkeypatch):
        """
        Delivery failing is our problem, not the user's: the alert stays active
        so the next tick can retry. This is the behaviour `_fire` exists for, and
        it has to survive being driven over HTTP.
        """
        import notifications

        async def refuses(*a, **k):
            raise notifications.EmailSendFailed("Resend said no")

        monkeypatch.setattr(notifications, "send_email", refuses)
        alert_id = self._seed(db, target_rate=55.0)

        assert live.post(URL, headers={"Authorization": f"Bearer {SECRET}"}).status_code == 200

        is_active, last_triggered = self._alert(db, alert_id)
        assert is_active is True, "a failed delivery must not spend the alert"
        assert last_triggered is None
