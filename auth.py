"""
Console sign-in, own account and user management (admins), with an audit log
"""
import json
import logging
import re
import secrets
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from jobs_queue import get_redis
from models import AuditEvent, User, UserRole, db, utcnow
from security import admin_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 15 * 60  # seconds
MIN_PASSWORD_LENGTH = 12
REVEAL_TTL = 300  # seconds a generated password can be viewed once
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# No look-alike characters (0/O, 1/l/I) so passwords can be read out
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

ROLE_DESCRIPTIONS = {
    UserRole.OPERATOR: "Calls, orders and voice messages; can update statuses and notes.",
    UserRole.ADMIN: "Everything operators can do, plus managing users and the activity log.",
}

# Pages a user with a temporary password may still open
PASSWORD_CHANGE_ALLOWED = {"auth.account", "auth.change_password", "auth.logout", "static", "health_check"}


# --- Helpers -------------------------------------------------------------------

def audit(action, target=None, detail=None, actor=None):
    """Record a security-relevant action; never let auditing break the request"""
    try:
        actor = actor if actor is not None else (current_user if current_user.is_authenticated else None)
        db.session.add(AuditEvent(
            action=action,
            actor_id=actor.id if actor else None,
            target_id=target.id if target else None,
            detail=(detail or "")[:255] or None,
            ip_address=request.remote_addr,
        ))
        db.session.commit()
    except Exception as e:
        logger.error(f"Audit event {action} not recorded: {e}")
        db.session.rollback()


def generate_password():
    groups = ["".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)


def password_problem(password, confirm=None):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if confirm is not None and password != confirm:
        return "The passwords don't match."
    return None


def _reveal_password(user, password):
    """Show a generated password to the admin once, without putting it in the cookie"""
    token = secrets.token_urlsafe(16)
    try:
        get_redis().setex(f"reveal:{token}", REVEAL_TTL, json.dumps({"user_id": user.id, "password": password}))
        return token
    except Exception as e:
        logger.error(f"Could not store the generated password for display: {e}")
        return None


def _pop_revealed(token):
    if not token:
        return None
    try:
        key = f"reveal:{token}"
        pipe = get_redis().pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _ = pipe.execute()
    except Exception:
        return None
    if not raw:
        return None
    data = json.loads(raw)
    user = db.session.get(User, data["user_id"])
    return {"user": user, "password": data["password"]} if user else None


def active_admin_count(excluding=None):
    query = User.query.filter_by(role=UserRole.ADMIN, is_active_user=True)
    if excluding is not None:
        query = query.filter(User.id != excluding.id)
    return query.count()


def _throttle_key(ip):
    return f"login:failed:{ip}"


def _is_throttled(ip):
    try:
        return int(get_redis().get(_throttle_key(ip)) or 0) >= MAX_FAILED_LOGINS
    except Exception as e:
        logger.warning(f"Login throttle unavailable: {e}")
        return False


def _record_failed_login(ip):
    try:
        key = _throttle_key(ip)
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, FAILED_LOGIN_WINDOW)
        pipe.execute()
    except Exception as e:
        logger.warning(f"Login throttle unavailable: {e}")


def _reset_failed_logins(ip):
    try:
        get_redis().delete(_throttle_key(ip))
    except Exception:
        pass


def _safe_next_url(target):
    """Only allow redirects within this site"""
    if not target:
        return url_for("dashboard")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for("dashboard")
    return target


@auth_bp.app_context_processor
def inject_now_year():
    return {"now_year": utcnow().year}


@auth_bp.before_app_request
def require_password_change():
    """A temporary password must be replaced before using the console"""
    if (
        current_user.is_authenticated
        and current_user.must_change_password
        and request.endpoint not in PASSWORD_CHANGE_ALLOWED
        and not request.path.startswith("/webhook/")
    ):
        return redirect(url_for("auth.account"))
    return None


# --- Sign-in -------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        username = request.form.get("username", "").strip()
        if _is_throttled(ip):
            logger.warning(f"Login throttled for {ip}")
            audit("sign_in_throttled", detail=username)
            flash("Too many sign-in attempts. Please try again in 15 minutes.", "danger")
            return render_template("login.html"), 429

        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.is_active and user.check_password(password):
            _reset_failed_logins(ip)
            login_user(user, remember=False)
            user.last_login_at = utcnow()
            db.session.commit()
            audit("sign_in", target=user, actor=user)
            logger.info(f"User {user.username} logged in")
            if user.must_change_password:
                return redirect(url_for("auth.account"))
            return redirect(_safe_next_url(request.args.get("next")))

        _record_failed_login(ip)
        audit("sign_in_failed", target=user, detail=username)
        logger.warning(f"Failed login for '{username}' from {ip}")
        flash("Incorrect username or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# --- Own account ----------------------------------------------------------------

@auth_bp.route("/account", methods=["GET"])
def account():
    recent = (
        AuditEvent.query.filter(
            AuditEvent.target_id == current_user.id,
            AuditEvent.action.in_(["sign_in", "sign_in_failed", "password_changed", "password_reset"]),
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "account.html", recent=recent, role_description=ROLE_DESCRIPTIONS[current_user.role],
        min_length=MIN_PASSWORD_LENGTH,
    )


@auth_bp.route("/account/password", methods=["POST"])
def change_password():
    user = current_user._get_current_object()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    problem = password_problem(new, request.form.get("confirm_password", ""))
    if not user.check_password(current):
        problem = "Your current password is incorrect."
    elif not problem and user.check_password(new):
        problem = "Choose a password different from the current one."
    if problem:
        flash(problem, "danger")
        return redirect(url_for("auth.account"))

    user.set_password(new)  # also signs out other sessions
    db.session.commit()
    login_user(user)  # keep this session with the new token
    audit("password_changed", target=user)
    flash("Your password has been changed. Other sessions were signed out.", "success")
    return redirect(url_for("dashboard"))


# --- User management (admins) ---------------------------------------------------------

@auth_bp.route("/users", methods=["GET"])
@admin_required
def users():
    all_users = User.query.order_by(User.is_active_user.desc(), User.username).all()
    activity = AuditEvent.query.order_by(AuditEvent.created_at.desc()).limit(15).all()
    return render_template(
        "users.html",
        users=all_users,
        roles=list(UserRole),
        role_descriptions=ROLE_DESCRIPTIONS,
        activity=activity,
        revealed=_pop_revealed(request.args.get("reveal")),
        min_length=MIN_PASSWORD_LENGTH,
    )


def _profile_problem(username, email):
    if username is not None and not USERNAME_RE.match(username):
        return "Usernames are 3–40 characters: lowercase letters, digits, dots, dashes or underscores."
    if email and not EMAIL_RE.match(email):
        return "Enter a valid email address or leave it empty."
    return None


def _issue_password(user, mode, manual):
    """Set a temporary password: generated (shown once) or typed by the admin"""
    if mode == "manual":
        problem = password_problem(manual)
        if problem:
            return None, problem
        user.set_password(manual, temporary=True)
        return None, None
    password = generate_password()
    user.set_password(password, temporary=True)
    return password, None


@auth_bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip() or None
    role_name = request.form.get("role", "OPERATOR")
    problem = _profile_problem(username, email)
    if not problem and role_name not in UserRole.__members__:
        problem = "Choose a role."
    if not problem and User.query.filter_by(username=username).first():
        problem = "A user with this username already exists."
    if problem:
        flash(problem, "danger")
        return redirect(url_for("auth.users"))

    user = User(
        username=username,
        full_name=request.form.get("full_name", "").strip() or None,
        email=email,
        role=UserRole[role_name],
        created_by_id=current_user.id,
    )
    password, problem = _issue_password(user, request.form.get("password_mode"), request.form.get("password", ""))
    if problem:
        flash(problem, "danger")
        return redirect(url_for("auth.users"))
    db.session.add(user)
    db.session.commit()
    audit("user_created", target=user, detail=user.role.value)
    flash(f"User {username} created. They will choose their own password at first sign-in.", "success")
    token = _reveal_password(user, password) if password else None
    return redirect(url_for("auth.users", reveal=token) if token else url_for("auth.users"))


@auth_bp.route("/users/<int:user_id>", methods=["POST"])
@admin_required
def update_user(user_id):
    user = db.get_or_404(User, user_id)
    email = request.form.get("email", "").strip() or None
    role_name = request.form.get("role", user.role.name)
    problem = _profile_problem(None, email)
    if not problem and role_name not in UserRole.__members__:
        problem = "Choose a role."
    new_role = UserRole[role_name] if not problem else user.role
    if not problem and user.is_admin and new_role != UserRole.ADMIN:
        if user.id == current_user.id:
            problem = "You can't remove your own admin role."
        elif active_admin_count(excluding=user) == 0:
            problem = "At least one active admin is required."
    if problem:
        flash(problem, "danger")
        return redirect(url_for("auth.users"))

    changes = []
    if new_role != user.role:
        changes.append(f"role {user.role.value} → {new_role.value}")
        user.role = new_role
    full_name = request.form.get("full_name", "").strip() or None
    if full_name != user.full_name:
        changes.append("name")
        user.full_name = full_name
    if email != user.email:
        changes.append("email")
        user.email = email
    db.session.commit()
    if changes:
        audit("user_updated", target=user, detail=", ".join(changes))
    flash(f"User {user.username} updated.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You can't disable your own account.", "danger")
    elif user.is_active_user and user.is_admin and active_admin_count(excluding=user) == 0:
        flash("At least one active admin is required.", "danger")
    else:
        user.is_active_user = not user.is_active_user
        user.rotate_session()  # a disabled user is signed out immediately
        db.session.commit()
        audit("user_enabled" if user.is_active_user else "user_disabled", target=user)
        state = "enabled" if user.is_active_user else "disabled and signed out"
        flash(f"User {user.username} {state}.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:user_id>/password", methods=["POST"])
@admin_required
def reset_password(user_id):
    user = db.get_or_404(User, user_id)
    password, problem = _issue_password(user, request.form.get("password_mode"), request.form.get("password", ""))
    if problem:
        flash(problem, "danger")
        return redirect(url_for("auth.users"))
    db.session.commit()
    if user.id == current_user.id:
        login_user(user)  # keep the admin's own session
    audit("password_reset", target=user)
    flash(f"New temporary password set for {user.username}. They were signed out and must change it at next sign-in.", "success")
    token = _reveal_password(user, password) if password else None
    return redirect(url_for("auth.users", reveal=token) if token else url_for("auth.users"))
