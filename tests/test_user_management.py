import re

from flask import g

from models import AuditEvent, User, UserRole, db
from tests.conftest import PASSWORD, get_csrf_token, login


class Fresh:
    """Test client that clears `g` before each request.

    Tests share one app context, so `g` would carry the previous client's
    signed-in user and CSRF token into the next client's request.
    """

    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        method = getattr(self.client, name)
        if name in ("get", "post"):
            def call(*args, **kwargs):
                for key in list(vars(g)):
                    g.pop(key, None)
                return method(*args, **kwargs)
            return call
        return method


def two_clients(app):
    return Fresh(app.test_client()), Fresh(app.test_client())


def admin_post(client, path, **data):
    token = get_csrf_token(client, "/users")
    return client.post(path, data={**data, "csrf_token": token})


def user(name):
    db.session.expire_all()
    return User.query.filter_by(username=name).one()


def actions():
    return [e.action for e in AuditEvent.query.order_by(AuditEvent.id)]


# --- Sessions --------------------------------------------------------------------

def test_disabling_a_user_signs_them_out_immediately(app):
    operator_client, admin_client = two_clients(app)
    login(operator_client, "operator")
    assert operator_client.get("/calls").status_code == 200

    login(admin_client, "admin")
    admin_post(admin_client, f"/users/{user('operator').id}/toggle")
    assert operator_client.get("/calls").status_code == 302  # session no longer valid


def test_password_reset_signs_out_existing_sessions(app):
    operator_client, admin_client = two_clients(app)
    login(operator_client, "operator")
    login(admin_client, "admin")
    admin_post(admin_client, f"/users/{user('operator').id}/password", password_mode="generate")
    assert operator_client.get("/calls").status_code == 302


# --- Temporary passwords -------------------------------------------------------------

def test_generated_password_is_shown_once_and_never_in_the_cookie(client, app):
    login(client, "admin")
    resp = admin_post(client, "/users", username="new.user", full_name="New User", role="OPERATOR",
                      password_mode="generate")
    assert resp.status_code == 302 and "reveal=" in resp.headers["Location"]
    for cookie in client._cookies.values():
        assert "-" not in cookie.value or len(cookie.value) > 100  # no plain password in the cookie

    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    password = re.search(r'id="revealed-password">([^<]+)<', page).group(1)
    assert re.fullmatch(r"([A-Za-z0-9]{4}-){3}[A-Za-z0-9]{4}", password)
    assert user("new.user").check_password(password)
    assert user("new.user").must_change_password
    # second visit: gone
    assert 'id="revealed-password"' not in client.get(resp.headers["Location"]).get_data(as_text=True)


def test_temporary_password_must_be_changed_before_using_the_console(app):
    admin_client, new_client = two_clients(app)
    login(admin_client, "admin")
    admin_post(admin_client, "/users", username="temp.user", role="OPERATOR",
               password_mode="manual", password="temporary-pass-1")

    resp = login(new_client, "temp.user", "temporary-pass-1")
    assert resp.headers["Location"].endswith("/account")
    assert new_client.get("/calls").headers["Location"].endswith("/account")

    token = get_csrf_token(new_client, "/account")
    resp = new_client.post("/account/password", data={
        "current_password": "temporary-pass-1", "new_password": "my-own-password-2",
        "confirm_password": "my-own-password-2", "csrf_token": token})
    assert resp.status_code == 302
    assert new_client.get("/calls").status_code == 200  # same session still valid
    assert not user("temp.user").must_change_password
    assert "password_changed" in actions()


def test_change_password_validation(client, app):
    login(client, "operator")
    token = get_csrf_token(client, "/account")
    for data, message in [
        ({"current_password": "wrong", "new_password": "x" * 12, "confirm_password": "x" * 12}, "current password is incorrect"),
        ({"current_password": PASSWORD, "new_password": "short", "confirm_password": "short"}, "at least 12"),
        ({"current_password": PASSWORD, "new_password": "x" * 12, "confirm_password": "y" * 12}, "don&#39;t match"),
        ({"current_password": PASSWORD, "new_password": PASSWORD, "confirm_password": PASSWORD}, "different from the current"),
    ]:
        client.post("/account/password", data={**data, "csrf_token": token})
        assert message in client.get("/account").get_data(as_text=True)
    assert user("operator").check_password(PASSWORD)


# --- Guardrails --------------------------------------------------------------------

def test_last_admin_cannot_be_demoted_or_disabled(client, app):
    login(client, "admin")
    admin = user("admin")
    admin_post(client, f"/users/{admin.id}", role="OPERATOR")
    assert user("admin").role == UserRole.ADMIN
    admin_post(client, f"/users/{admin.id}/toggle")
    assert user("admin").is_active_user


def test_admin_can_demote_another_admin_when_one_remains(client, app):
    login(client, "admin")
    admin_post(client, "/users", username="second.admin", role="ADMIN", password_mode="generate")
    second = user("second.admin")
    admin_post(client, f"/users/{second.id}", role="OPERATOR", full_name="Second", email="s@example.com")
    second = user("second.admin")
    assert second.role == UserRole.OPERATOR and second.email == "s@example.com"
    event = AuditEvent.query.filter_by(action="user_updated").one()
    assert "role admin → operator" in event.detail


def test_invalid_username_and_email_are_rejected(client, app):
    login(client, "admin")
    admin_post(client, "/users", username="Bad Name!", role="OPERATOR", password_mode="generate")
    admin_post(client, "/users", username="valid.name", email="not-an-email", role="OPERATOR", password_mode="generate")
    assert User.query.filter(User.username.in_(["bad name!", "valid.name"])).count() == 0


# --- Audit log ----------------------------------------------------------------------

def test_sign_ins_are_audited(client, app):
    login(client, "operator", "wrong-password")
    login(client, "operator")
    assert actions()[-2:] == ["sign_in_failed", "sign_in"]
    failed = AuditEvent.query.filter_by(action="sign_in_failed").one()
    assert failed.detail == "operator"  # the typed username, never the password


def test_users_page_shows_activity_and_account_link(client, app):
    login(client, "admin")
    admin_post(client, "/users", username="audited", role="OPERATOR", password_mode="generate")
    html = client.get("/users").get_data(as_text=True)
    assert "admin added audited as operator" in html
    assert "Recent activity" in html
    assert 'href="/account"' in html  # sidebar user chip


def test_account_page(client, app):
    login(client, "operator")
    html = client.get("/account").get_data(as_text=True)
    assert "My account" in html and "operator signed in" in html


def test_operator_cannot_manage_users(client, app):
    login(client, "operator")
    target = user("admin")
    assert client.post(f"/users/{target.id}/toggle", data={"csrf_token": get_csrf_token(client, "/account")}).status_code == 403


def test_user_action_menu_is_not_clipped_by_the_table(client, app):
    """The table scrolls horizontally (overflow), which clips absolutely positioned menus"""
    login(client, "admin")
    html = client.get("/users").get_data(as_text=True)
    assert """data-bs-popper-config='{"strategy": "fixed"}'""" in html
