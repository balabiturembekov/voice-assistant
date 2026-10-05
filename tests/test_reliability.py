from datetime import timedelta

import app as app_module
from models import Call, Conversation, Order, VoiceMessage, db, utcnow
from retention import ANONYMIZED_PHONE, anonymize_calls_older_than
from tests.conftest import get_csrf_token, login


def test_calls_filter_with_unknown_status(client):
    login(client, "operator")
    assert client.get("/calls?status=NOPE").status_code == 200


def test_api_with_empty_body_returns_400(client):
    login(client, "operator")
    token = get_csrf_token(client, "/calls")
    call = Call(call_sid="CAx", phone_number="+491", language="de")
    db.session.add(call)
    db.session.commit()
    resp = client.post(
        f"/api/calls/{call.id}/status",
        data="not json",
        headers={"X-CSRFToken": token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["checks"] == {"database": "ok", "redis": "ok"}


def test_health_reports_redis_down(client, fake_redis, monkeypatch):
    def broken_ping():
        raise ConnectionError("down")

    monkeypatch.setattr(fake_redis, "ping", broken_ping)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json()["checks"]["redis"] == "error"


def test_afterbuy_hits_are_cached(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_module, "_fetch_order_from_afterbuy",
        lambda n: calls.append(n) or {"order_id": n, "invoice_number": n},
    )
    assert app_module.get_order_from_afterbuy("123")["order_id"] == "123"
    assert app_module.get_order_from_afterbuy("123")["order_id"] == "123"
    assert calls == ["123"]


def test_afterbuy_misses_are_not_cached(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "_fetch_order_from_afterbuy", lambda n: calls.append(n))
    app_module.get_order_from_afterbuy("404")
    app_module.get_order_from_afterbuy("404")
    assert len(calls) == 2


def test_afterbuy_works_when_redis_is_down(app, fake_redis, monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(fake_redis, "get", broken)
    monkeypatch.setattr(fake_redis, "setex", broken)
    monkeypatch.setattr(app_module, "_fetch_order_from_afterbuy", lambda n: {"order_id": n})
    assert app_module.get_order_from_afterbuy("1") == {"order_id": "1"}


def test_login_throttling(client):
    for _ in range(10):
        login(client, "admin", "wrong-password")
    resp = login(client, "admin")  # even the right password is blocked now
    assert resp.status_code == 429


def test_retention_anonymizes_old_calls(app):
    old = Call(call_sid="CAold", phone_number="+4915100000001", language="de",
               created_at=utcnow() - timedelta(days=100))
    new = Call(call_sid="CAnew", phone_number="+4915100000002", language="de")
    db.session.add_all([old, new])
    db.session.commit()
    db.session.add_all([
        Conversation(call_id=old.id, step="order_input", user_input="24896241", bot_response="Danke Max"),
        Order(call_id=old.id, order_number="24896241", notes="Max Mustermann"),
        VoiceMessage(call_id=old.id, recording_sid="REold", recording_url="https://x", transcription_text="secret"),
    ])
    db.session.commit()

    assert anonymize_calls_older_than(90) == 1
    assert anonymize_calls_older_than(90) == 0  # idempotent

    db.session.expire_all()
    assert old.phone_number == ANONYMIZED_PHONE
    assert old.anonymized_at is not None
    assert Conversation.query.filter_by(call_id=old.id).one().user_input is None
    assert Order.query.filter_by(call_id=old.id).one().notes is None
    vm = VoiceMessage.query.filter_by(call_id=old.id).one()
    assert vm.transcription_text is None and vm.recording_url is None
    assert new.phone_number == "+4915100000002"


def test_migrations_match_models(tmp_path):
    """Alembic migrations must produce exactly the schema the models describe"""
    import os
    import subprocess
    import sys

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    project_dir = os.path.dirname(os.path.abspath(app_module.__file__))
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"],
        cwd=project_dir,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    with create_engine(db_url).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), db.metadata) == []
