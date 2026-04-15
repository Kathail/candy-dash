"""Authentication routes: login, logout, change password."""

from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from app import db, limiter
from app.helpers import safe_redirect, audit
from app.models import User, Payment, RouteStop

bp = Blueprint("auth", __name__, url_prefix="")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    """Show login form and authenticate user."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(username=username).first()

        # Always run password check to prevent timing-based username enumeration
        if user is not None:
            password_ok = user.check_password(password)
        else:
            # Burn the same time as a real check
            from werkzeug.security import generate_password_hash
            generate_password_hash(password)
            password_ok = False

        if user is None or not password_ok or not user.is_active:
            if user:
                audit("login_failed", f"Failed login attempt for '{username}'", user_id=user.id)
                db.session.commit()
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html"), 401

        login_user(user, remember=remember)
        session.permanent = True
        audit("login", f"'{user.username}' logged in", user_id=user.id)
        db.session.commit()
        flash(f"Welcome back, {user.username}!", "success")

        next_page = request.args.get("next")
        return redirect(safe_redirect(next_page))

    return render_template("auth/login.html")


@bp.route("/demo")
@limiter.limit("5 per minute")
def demo():
    """Log in as the read-only demo user."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    user = User.query.filter_by(username="demo", role="demo").first()
    if not user or not user.is_active:
        flash("Demo account is not available.", "error")
        return redirect(url_for("auth.login"))

    login_user(user, remember=False)
    flash("Welcome to the demo! Browse freely — all changes are disabled.", "info")
    return redirect(url_for("dashboard.index"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Log the current user out."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile")
@login_required
def profile():
    """User's own profile page."""
    # Stats for this user
    payments_recorded = Payment.query.filter_by(recorded_by=current_user.id).count()
    stops_completed = RouteStop.query.filter_by(created_by=current_user.id, completed=True).count()
    total_collected = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.recorded_by == current_user.id)
        .scalar()
    )

    return render_template(
        "auth/profile.html",
        payments_recorded=payments_recorded,
        stops_completed=stops_completed,
        total_collected=total_collected,
    )


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per minute", methods=["POST"])
def change_password():
    """Allow the logged-in user to change their own password."""
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(old_password):
            flash("Current password is incorrect.", "error")
            return render_template("auth/change_password.html"), 400

        if len(new_password) < 12:
            flash("New password must be at least 12 characters long.", "error")
            return render_template("auth/change_password.html"), 400

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return render_template("auth/change_password.html"), 400

        current_user.set_password(new_password)
        audit("password_changed", f"'{current_user.username}' changed their password")
        db.session.commit()
        flash("Your password has been updated.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("auth/change_password.html")
