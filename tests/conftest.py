import os
import sys

import fakeredis
import pytest
from twilio.request_validator import RequestValidator

# Settings must exist before config.py / app.py are imported
TEST_ENV = {
    "SECRET_KEY": "test-secret",
    "TWILIO_AUTH_TOKEN": "test-twilio-token",
    "TWILIO_VALIDATE_REQUESTS": "True",
    "AFTERBUY_PARTNER_ID": "1",
    "AFTERBUY_PARTNER_TOKEN": "t",
    "AFTERBUY_ACCOUNT_TOKEN": "t",
    "AFTERBUY_USER_ID": "u",
    "AFTERBUY_USER_PASSWORD": "p",
    "FLASK_DEBUG": "False",
    "SESSION_COOKIE_SECURE": "False",
    "DATABASE_URL": "sqlite://",
    "QUEUE_SYNC": "True",
    "TRANSCRIPTION_SERVICE": "twilio",
}
os.environ.update(TEST_ENV)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app  # noqa: E402
from jobs_queue import set_redis  # noqa: E402
from models import User, UserRole, db  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fake_redis():
    connection = fakeredis.FakeRedis()
    set_redis(connection)
    yield connection
    set_redis(None)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        db.create_all()
        for name, role in (("admin", UserRole.ADMIN), ("operator", UserRole.OPERATOR)):
            user = User(username=name, role=role)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def get_csrf_token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    marker = 'name="csrf-token" content="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


def login(client, username, password=PASSWORD):
    token = get_csrf_token(client)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
    )


def post_webhook(client, path, params):
    """POST to a Twilio webhook with a valid X-Twilio-Signature"""
    url = f"http://localhost{path}"
    signature = RequestValidator(TEST_ENV["TWILIO_AUTH_TOKEN"]).compute_signature(url, params)
    return client.post(path, data=params, headers={"X-Twilio-Signature": signature})
