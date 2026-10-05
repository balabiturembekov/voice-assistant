import pytest

import recordings
from models import Call, VoiceMessage, db
from tests.conftest import login

ACCOUNT = "AC" + "a" * 32
RECORDING = "RE" + "b" * 32
URL = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Recordings/{RECORDING}"
MP3 = b"ID3" + b"\x00" * 2000


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


@pytest.fixture
def message(app):
    call = Call(call_sid="CArec", phone_number="+491", language="de")
    db.session.add(call)
    db.session.commit()
    vm = VoiceMessage(call_id=call.id, recording_sid=RECORDING, recording_url=URL, duration_seconds=12)
    db.session.add(vm)
    db.session.commit()
    return vm


@pytest.fixture
def twilio(monkeypatch):
    requests_made = []

    def fake_get(url, auth=None, timeout=None):
        requests_made.append((url, auth))
        return FakeResponse(200, MP3)

    monkeypatch.setattr(recordings.requests, "get", fake_get)
    return requests_made


def test_audio_requires_sign_in(client, message, twilio):
    resp = client.get(f"/voice-messages/{message.id}/audio")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert twilio == []


def test_audio_is_fetched_with_account_auth_and_cached(client, message, twilio):
    login(client, "operator")
    resp = client.get(f"/voice-messages/{message.id}/audio")
    assert resp.status_code == 200
    assert resp.mimetype == "audio/mpeg"
    assert resp.data == MP3
    assert twilio == [(URL + ".mp3", (ACCOUNT, "test-twilio-token"))]

    client.get(f"/voice-messages/{message.id}/audio")
    assert len(twilio) == 1  # second play served from the cache


def test_audio_supports_seeking(client, message, twilio):
    login(client, "operator")
    resp = client.get(f"/voice-messages/{message.id}/audio", headers={"Range": "bytes=100-199"})
    assert resp.status_code == 206
    assert resp.data == MP3[100:200]


def test_twilio_error_returns_502(client, message, monkeypatch):
    monkeypatch.setattr(recordings.requests, "get", lambda *a, **k: FakeResponse(401))
    login(client, "operator")
    assert client.get(f"/voice-messages/{message.id}/audio").status_code == 502


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/2010-04-01/Accounts/%s/Recordings/%s" % (ACCOUNT, RECORDING),
        "http://api.twilio.com/2010-04-01/Accounts/%s/Recordings/%s" % (ACCOUNT, RECORDING),
        "https://api.twilio.com/2010-04-01/Accounts/%s/Calls/%s" % (ACCOUNT, RECORDING),
        "https://api.twilio.com/../../etc/passwd",
        None,
    ],
)
def test_only_twilio_recording_urls_are_fetched(url):
    assert recordings.parse_recording_url(url) is None
    with pytest.raises(recordings.RecordingUnavailable):
        recordings.fetch_recording(url)


def test_call_page_uses_console_player(client, message):
    login(client, "operator")
    html = client.get(f"/calls/{message.call_id}").get_data(as_text=True)
    assert f'src="/voice-messages/{message.id}/audio"' in html
    assert "api.twilio.com" not in html
