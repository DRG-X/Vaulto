"""
Rate alerts, from "target hit" to "mail actually left the building".

Every test here started as a reproduction of something that was silently
broken. Silence is the theme: an alert that never fires, an alert consumed by
a send that failed, and an address that was never captured look identical from
the outside — the user just never hears anything, and the logs say the run
completed.
"""

import datetime
from types import SimpleNamespace

import httpx
import pytest

import notifications
import scheduler
from notifications import EmailNotConfigured, EmailSendFailed


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result


class FakeSession:
    """Just enough Session for the notification path."""

    def __init__(self, user=None):
        self.user = user
        self.commits = 0

    def query(self, model):
        return FakeQuery(self.user)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def make_alert(**kw):
    defaults = dict(
        id=1,
        clerk_user_id="user_123",
        from_currency="AUD",
        to_currency="INR",
        amount=1000.0,
        target_rate=55.0,
        provider=None,
        pay_out_method=None,
        notify_email=True,
        notify_whatsapp=False,
        is_active=True,
        last_triggered=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def user(email="student@example.com"):
    return SimpleNamespace(clerk_user_id="user_123", email=email)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("ALERT_FROM_EMAIL", raising=False)
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return original(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


class TestEmailSending:
    @pytest.mark.asyncio
    async def test_a_missing_api_key_is_raised_not_swallowed(self, monkeypatch):
        """
        It used to log a warning and return, which the caller read as success
        and then paused the alert on the strength of it.
        """
        with pytest.raises(EmailNotConfigured):
            await notifications.send_email("a@b.com", "subject", "body")

    @pytest.mark.asyncio
    async def test_a_sent_mail_carries_the_message(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"id": "msg_1"})

        transport(monkeypatch, handler)

        await notifications.send_email("student@example.com", "Rate hit", "1 AUD = 55")

        assert seen["url"] == notifications.RESEND_ENDPOINT
        assert seen["auth"] == "Bearer re_test"
        assert "student@example.com" in seen["body"]
        assert "1 AUD = 55" in seen["body"]

    @pytest.mark.asyncio
    async def test_a_rejected_send_raises_with_the_providers_reason(self, monkeypatch):
        """
        The most likely production failure: the from-domain is not verified.
        Resend explains it in the body, so that has to reach the logs.
        """
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        transport(monkeypatch, lambda request: httpx.Response(
            403, json={"message": "The vaulto.in domain is not verified"}
        ))

        with pytest.raises(EmailSendFailed) as excinfo:
            await notifications.send_email("a@b.com", "s", "b")

        assert "not verified" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_a_transport_failure_raises(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")

        def handler(request):
            raise httpx.ConnectError("no route to host")

        transport(monkeypatch, handler)

        with pytest.raises(EmailSendFailed):
            await notifications.send_email("a@b.com", "s", "b")

    @pytest.mark.asyncio
    async def test_the_from_address_is_configurable(self, monkeypatch):
        """Hardcoding an unverified domain is what makes every send 403."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        monkeypatch.setenv("ALERT_FROM_EMAIL", "Vaulto <onboarding@resend.dev>")
        seen = {}

        def handler(request):
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"id": "m"})

        transport(monkeypatch, handler)
        await notifications.send_email("a@b.com", "s", "b")

        assert "onboarding@resend.dev" in seen["body"]


class TestNotificationDispatch:
    @pytest.mark.asyncio
    async def test_a_user_with_no_address_on_file_is_not_a_silent_success(
        self, monkeypatch
    ):
        """
        THE original bug. Clerk's default session JWT carries no email claim,
        so every user row was created with email=None, so this branch was
        never taken — and it returned as though it had done its job.
        """
        monkeypatch.setattr(
            notifications, "send_email", _never_called
        )
        db = FakeSession(user=user(email=None))

        sent = await scheduler.send_alert_notification(
            make_alert(), 56.0, "Wise", db
        )

        assert sent is False

    @pytest.mark.asyncio
    async def test_a_missing_address_is_fetched_from_clerk(self, monkeypatch):
        """The address exists — it is in Clerk, it was just never copied here."""
        monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test")

        def handler(request):
            if "api.clerk.com" in str(request.url):
                return httpx.Response(200, json={
                    "primary_email_address_id": "idn_2",
                    "email_addresses": [
                        {"id": "idn_1", "email_address": "old@example.com"},
                        {"id": "idn_2", "email_address": "primary@example.com"},
                    ],
                })
            return httpx.Response(200, json={"id": "msg"})

        transport(monkeypatch, handler)
        monkeypatch.setenv("RESEND_API_KEY", "re_test")

        db_user = user(email=None)
        db = FakeSession(user=db_user)

        sent = await scheduler.send_alert_notification(
            make_alert(), 56.0, "Wise", db
        )

        assert sent is True
        # Persisted, so the next alert does not pay for the lookup again.
        assert db_user.email == "primary@example.com"

    @pytest.mark.asyncio
    async def test_a_scoped_alert_does_not_claim_to_know_the_market(self, monkeypatch):
        captured = {}

        async def fake_send(to, subject, text, **kw):
            captured["text"] = text

        monkeypatch.setattr(notifications, "send_email", fake_send)
        db = FakeSession(user=user())

        await scheduler.send_alert_notification(
            make_alert(provider="Wise"), 56.0, "Wise", db
        )

        assert "Wise" in captured["text"]
        assert "Best provider right now" not in captured["text"]

    @pytest.mark.asyncio
    async def test_a_failed_send_is_reported_to_the_caller(self, monkeypatch):
        async def fake_send(to, subject, text, **kw):
            raise EmailSendFailed("Resend is down")

        monkeypatch.setattr(notifications, "send_email", fake_send)
        db = FakeSession(user=user())

        sent = await scheduler.send_alert_notification(
            make_alert(), 56.0, "Wise", db
        )

        assert sent is False


async def _never_called(*a, **k):                    # pragma: no cover
    raise AssertionError("send_email must not be called without an address")


class TestTriggerBookkeeping:
    """
    What happens to the alert row once the target is hit.

    Pausing on a send that failed is how a user loses an alert AND the mail:
    the row goes inactive, nothing arrives, and nothing in the system knows.
    """

    @pytest.mark.asyncio
    async def test_a_successful_send_pauses_the_alert(self, monkeypatch):
        alert = make_alert()
        monkeypatch.setattr(
            scheduler, "send_alert_notification", _succeeds
        )

        fired = await scheduler._fire(alert, 56.0, "Wise", _CommitCounter())

        assert fired is True
        assert alert.is_active is False
        assert alert.last_triggered is not None

    @pytest.mark.asyncio
    async def test_a_failed_send_leaves_the_alert_armed(self, monkeypatch):
        """Reproduction: the alert used to be consumed by a send that failed."""
        alert = make_alert()
        monkeypatch.setattr(scheduler, "send_alert_notification", _fails)

        fired = await scheduler._fire(alert, 56.0, "Wise", _CommitCounter())

        assert fired is False
        assert alert.is_active is True, "a failed send must not consume the alert"
        assert alert.last_triggered is None


class _CommitCounter:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


async def _succeeds(alert, rate, provider, db):
    return True


async def _fails(alert, rate, provider, db):
    return False
