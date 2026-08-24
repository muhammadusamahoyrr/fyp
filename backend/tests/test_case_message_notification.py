"""A case message must reach the other party.

Case messaging is the working channel between client and lawyer, and it had no
NotificationType at all — a message was stored and surfaced only if the other
side happened to reopen the case. A lawyer asking for a document, or a client
answering, could sit unread indefinitely while both believed the ball was in the
other's court.
"""
import pytest

from app.core.constants import NotificationType
from app.services import case_service as cs

CASE = {"_id": "c1", "title": "Plot dispute", "client_id": "CL1", "lawyer_id": "LW1"}


@pytest.fixture
def sent(monkeypatch):
    """Capture notifications instead of writing them."""
    out = []

    async def _find(case_id):
        return dict(CASE)

    async def _add(case_id, msg):
        return True

    async def _capture(user_id, ntype, title, body, payload=None):
        out.append({"to": user_id, "type": ntype, "title": title,
                    "body": body, "payload": payload})

    # Patch the FUNCTION on the real module, not the sys.modules entry.
    # `from app.services import notification_service` resolves through the
    # parent package's attribute, so swapping the sys.modules entry only works
    # while nothing else has imported the real module — which made these tests
    # pass alone and fail in the full run.
    from app.services import notification_service as ns
    monkeypatch.setattr(ns, "create_notification", _capture)
    monkeypatch.setattr(cs.case_repo, "find_by_id", _find)
    monkeypatch.setattr(cs.case_repo, "add_message", _add)
    monkeypatch.setattr(cs, "_assert_access", lambda *a, **k: None)
    return out


class TestItReachesTheOtherParty:
    async def test_a_client_message_notifies_the_lawyer(self, sent):
        await cs.send_message("c1", "CL1", "client", "Ali", "Sending the fard today")
        assert len(sent) == 1
        assert sent[0]["to"] == "LW1"
        assert sent[0]["type"] == NotificationType.CASE_MESSAGE

    async def test_a_lawyer_message_notifies_the_client(self, sent):
        await cs.send_message("c1", "LW1", "lawyer", "Adv. Khan", "Send me the fard")
        assert len(sent) == 1
        assert sent[0]["to"] == "CL1"

    async def test_the_sender_is_never_notified(self, sent):
        await cs.send_message("c1", "CL1", "client", "Ali", "hello")
        assert all(n["to"] != "CL1" for n in sent)


class TestTheContent:
    async def test_the_preview_carries_the_message(self, sent):
        """An urgent request should be legible without opening the app."""
        await cs.send_message("c1", "LW1", "lawyer", "Adv. Khan",
                              "Send me the fard before Thursday")
        assert "fard before Thursday" in sent[0]["body"]

    async def test_a_long_message_is_truncated(self, sent):
        await cs.send_message("c1", "LW1", "lawyer", "K", "x" * 500)
        assert len(sent[0]["body"]) < 250
        assert sent[0]["body"].endswith("…")

    async def test_newlines_do_not_break_the_preview(self, sent):
        await cs.send_message("c1", "LW1", "lawyer", "K", "line one\nline two")
        assert "\n" not in sent[0]["body"]

    async def test_the_payload_can_deep_link(self, sent):
        await cs.send_message("c1", "LW1", "lawyer", "K", "hi")
        assert sent[0]["payload"]["case_id"] == "c1"
        assert sent[0]["payload"]["message_id"]


class TestItIsSafe:
    async def test_no_lawyer_engaged_means_nobody_to_tell(self, sent, monkeypatch):
        async def _find(case_id):
            return dict(CASE, lawyer_id=None)
        monkeypatch.setattr(cs.case_repo, "find_by_id", _find)
        msg = await cs.send_message("c1", "CL1", "client", "Ali", "hello")
        assert sent == []
        assert msg["text"] == "hello"      # the message itself still saved

    async def test_a_notification_failure_never_loses_the_message(self, monkeypatch):
        """The message is already written when we notify. Losing it because a
        notification blew up would be strictly worse than a silent message."""
        async def _find(case_id):
            return dict(CASE)
        async def _add(case_id, msg):
            return True
        async def _boom(*a, **k):
            raise RuntimeError("notification backend down")
        from app.services import notification_service as ns
        monkeypatch.setattr(ns, "create_notification", _boom)
        monkeypatch.setattr(cs.case_repo, "find_by_id", _find)
        monkeypatch.setattr(cs.case_repo, "add_message", _add)
        monkeypatch.setattr(cs, "_assert_access", lambda *a, **k: None)
        msg = await cs.send_message("c1", "CL1", "client", "Ali", "important")
        assert msg["text"] == "important"
