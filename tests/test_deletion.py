import pytest

import recordings
from models import AuditEvent, Call, Conversation, Order, User, VoiceMessage, db
from tests.conftest import get_csrf_token, login

ACCOUNT = "AC" + "a" * 32


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def twilio(monkeypatch):
    calls = {"deleted": [], "status": 204}

    def fake_delete(url, auth=None, timeout=None):
        calls["deleted"].append((url, auth))
        return FakeResponse(calls["status"])

    monkeypatch.setattr(recordings.requests, "delete", fake_delete)
    return calls


def make_call(n, with_voice=True):
    call = Call(call_sid=f"CAdel{n}", phone_number=f"+49151000000{n}", language="de")
    db.session.add(call)
    db.session.commit()
    db.session.add_all([
        Conversation(call_id=call.id, step="ivr_greeting", bot_response="Guten Tag"),
        Order(call_id=call.id, order_number=f"{n}00", lookup_result="found"),
    ])
    if with_voice:
        rec = "RE" + str(n) * 32
        db.session.add(VoiceMessage(call_id=call.id, recording_sid=rec, duration_seconds=5,
                                    recording_url=f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Recordings/{rec}"))
    db.session.commit()
    return call.id


def counts():
    db.session.expire_all()
    return (Call.query.count(), Conversation.query.count(), Order.query.count(), VoiceMessage.query.count())


def test_admin_deletes_a_call_with_everything(client, app, twilio):
    call_id = make_call(1)
    keep_id = make_call(2)
    login(client, "admin")
    token = get_csrf_token(client, f"/calls/{call_id}")
    resp = client.post(f"/calls/{call_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert counts() == (1, 1, 1, 1)  # only the other call remains
    assert db.session.get(Call, keep_id) is not None
    assert twilio["deleted"] == [(f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Recordings/{'R' + 'E' + '1' * 32}.json",
                                  (ACCOUNT, "test-twilio-token"))]
    event = AuditEvent.query.filter_by(action="calls_deleted").one()
    assert event.detail.startswith("1 call(s), 1 voice message(s), 1 order lookup(s)")


def test_call_is_kept_when_twilio_fails(client, app, twilio):
    twilio["status"] = 500
    call_id = make_call(1)
    login(client, "admin")
    token = get_csrf_token(client, f"/calls/{call_id}")
    client.post(f"/calls/{call_id}/delete", data={"csrf_token": token})
    assert counts() == (1, 1, 1, 1)
    assert "could not be deleted at Twilio" in client.get("/calls").get_data(as_text=True)


def test_recording_already_gone_at_twilio_is_fine(client, app, twilio):
    twilio["status"] = 404
    call_id = make_call(1)
    login(client, "admin")
    client.post(f"/calls/{call_id}/delete", data={"csrf_token": get_csrf_token(client, f"/calls/{call_id}")})
    assert counts() == (0, 0, 0, 0)


def test_bulk_delete_requires_typing_delete(client, app, twilio):
    ids = [make_call(1), make_call(2), make_call(3)]
    login(client, "admin")
    token = get_csrf_token(client, "/calls")
    client.post("/calls/delete", data={"csrf_token": token, "call_ids": ids[:2], "confirm": "yes"})
    assert counts()[0] == 3
    client.post("/calls/delete", data={"csrf_token": token, "call_ids": ids[:2], "confirm": "delete"})
    assert counts()[0] == 1
    assert db.session.get(Call, ids[2]) is not None


def test_operator_cannot_delete_and_sees_no_controls(client, app, twilio):
    call_id = make_call(1)
    login(client, "operator")
    token = get_csrf_token(client, "/calls")
    assert client.post(f"/calls/{call_id}/delete", data={"csrf_token": token}).status_code == 403
    assert client.post("/calls/delete", data={"csrf_token": token, "call_ids": [call_id], "confirm": "DELETE"}).status_code == 403
    assert counts()[0] == 1
    assert 'name="call_ids"' not in client.get("/calls").get_data(as_text=True)
    assert "deleteCallModal" not in client.get(f"/calls/{call_id}").get_data(as_text=True)


def test_admin_sees_delete_controls_with_summary(client, app, twilio):
    call_id = make_call(1)
    login(client, "admin")
    assert 'name="call_ids"' in client.get("/calls").get_data(as_text=True)
    html = client.get(f"/calls/{call_id}").get_data(as_text=True)
    assert "1 conversation event" in html and "1 order lookup" in html
    assert "including the recording at Twilio" in html


def test_delete_order_lookup_keeps_the_call(client, app, twilio):
    call_id = make_call(1, with_voice=False)
    order = Order.query.one()
    login(client, "admin")
    client.post(f"/orders/{order.id}/delete", data={"csrf_token": get_csrf_token(client, f"/orders/{order.id}")})
    assert counts() == (1, 1, 0, 0)
    assert AuditEvent.query.filter_by(action="order_deleted").count() == 1


def test_cli_deletes_all_calls_but_keeps_users(app, twilio):
    make_call(1)
    make_call(2)
    users_before = User.query.count()
    result = app.test_cli_runner().invoke(args=["delete-calls", "--all", "--yes"])
    assert result.exit_code == 0, result.output
    assert "About to delete 2 call(s)" in result.output and "Deleted 2 call(s)." in result.output
    assert counts() == (0, 0, 0, 0)
    assert User.query.count() == users_before
    assert len(twilio["deleted"]) == 2


def test_cli_needs_a_target(app):
    result = app.test_cli_runner().invoke(args=["delete-calls", "--yes"])
    assert result.exit_code != 0 and "Nothing to delete" in result.output
