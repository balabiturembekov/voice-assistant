"""
Dashboard authentication and user management
"""
import logging
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from jobs_queue import get_redis
from models import User, UserRole, db, utcnow
from security import admin_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 15 * 60  # seconds
MIN_PASSWORD_LENGTH = 12


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


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if _is_throttled(ip):
            logger.warning(f"Login throttled for {ip}")
            flash("Too many sign-in attempts. Please try again in 15 minutes.", "danger")
            return render_template("login.html"), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.is_active and user.check_password(password):
            _reset_failed_logins(ip)
            login_user(user, remember=False)
            user.last_login_at = utcnow()
            db.session.commit()
            logger.info(f"User {user.username} logged in")
            return redirect(_safe_next_url(request.args.get("next")))

        _record_failed_login(ip)
        logger.warning(f"Failed login for '{username}' from {ip}")
        flash("Incorrect username or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/users", methods=["GET"])
@admin_required
def users():
    all_users = User.query.order_by(User.username).all()
    return render_template("users.html", users=all_users, roles=list(UserRole))


@auth_bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role_name = request.form.get("role", "OPERATOR")

    if not username or role_name not in UserRole.__members__:
        flash("Enter a username and choose a role.", "danger")
    elif len(password) < MIN_PASSWORD_LENGTH:
        flash(f"The password must be at least {MIN_PASSWORD_LENGTH} characters long.", "danger")
    elif User.query.filter_by(username=username).first():
        flash("A user with this username already exists.", "danger")
    else:
        user = User(username=username, role=UserRole[role_name])
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info(f"User {username} created by {current_user.username}")
        flash(f"User {username} created.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You can't disable your own account.", "danger")
    else:
        user.is_active_user = not user.is_active_user
        db.session.commit()
        state = "enabled" if user.is_active_user else "disabled"
        logger.info(f"User {user.username} {state} by {current_user.username}")
        flash(f"User {user.username} {state}.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:user_id>/password", methods=["POST"])
@admin_required
def reset_password(user_id):
    user = db.get_or_404(User, user_id)
    password = request.form.get("password", "")
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"The password must be at least {MIN_PASSWORD_LENGTH} characters long.", "danger")
    else:
        user.set_password(password)
        db.session.commit()
        logger.info(f"Password of {user.username} reset by {current_user.username}")
        flash(f"Password for {user.username} changed.", "success")
    return redirect(url_for("auth.users"))
