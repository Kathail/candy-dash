"""Admin routes: user management and system operations."""

import csv
import io

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.helpers import admin_required
from app.models import User

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@login_required
def before_request():
    """Require login for all admin routes."""
    pass


@bp.route("/")
@admin_required
def index():
    """List all users."""
    users = User.query.order_by(User.username).all()
    return render_template("admin/index.html", users=users)


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def create_user():
    """Create a new user."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        role = request.form.get("role", "sales")

        if not username:
            flash("Username is required.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        if len(password) < 12:
            flash("Password must be at least 12 characters long.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        if User.query.filter_by(username=username).first():
            flash("A user with that username already exists.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        if email and User.query.filter_by(email=email).first():
            flash("A user with that email already exists.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        if role not in ("admin", "sales", "manager"):
            flash("Invalid role selected.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("admin.index"))

    return render_template("admin/user_form.html", editing=False)


@bp.route("/users/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(id):
    """Edit an existing user's profile."""
    user = db.session.get(User, id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        role = request.form.get("role", user.role)
        is_active = bool(request.form.get("is_active"))

        if not username:
            flash("Username is required.", "error")
            return render_template("admin/user_form.html", user=user, editing=True), 400

        if role not in ("admin", "sales", "manager"):
            flash("Invalid role selected.", "error")
            return render_template("admin/user_form.html", user=user, editing=True), 400

        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user.id:
            flash("A user with that username already exists.", "error")
            return render_template("admin/user_form.html", user=user, editing=True), 400

        if email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != user.id:
                flash("A user with that email already exists.", "error")
                return render_template("admin/user_form.html", user=user, editing=True), 400

        user.username = username
        user.email = email
        user.role = role
        user.is_active = is_active
        db.session.commit()

        flash(f"User '{username}' updated successfully.", "success")
        return redirect(url_for("admin.index"))

    return render_template("admin/user_form.html", user=user, editing=True)


@bp.route("/users/<int:id>/reset-password", methods=["POST"])
@admin_required
def reset_password(id):
    """Admin reset of a user's password."""
    user = db.session.get(User, id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.index"))

    new_password = request.form.get("new_password", "")

    if len(new_password) < 12:
        flash("Password must be at least 12 characters long.", "error")
        return redirect(url_for("admin.edit_user", id=user.id))

    user.set_password(new_password)
    db.session.commit()

    flash(f"Password for '{user.username}' has been reset.", "success")
    return redirect(url_for("admin.edit_user", id=user.id))


@bp.route("/seed", methods=["POST"])
@admin_required
def seed():
    """Trigger customer seed from seed_data.json."""
    from app.models import Customer
    from app.init_db import _seed_customers

    count_before = Customer.query.count()
    try:
        _seed_customers()
    except Exception as e:
        flash(f"Seed failed: {e}", "error")
        return redirect(url_for("admin.index"))

    count_after = Customer.query.count()
    added = count_after - count_before
    if added > 0:
        flash(f"Seeded {added} customers/leads.", "success")
    else:
        flash("No new records seeded (table may already have data, or seed_data.json not found).", "warning")
    return redirect(url_for("admin.index"))


@bp.route("/reimport", methods=["POST"])
@admin_required
def reimport():
    """Re-import customer data from an uploaded CSV.

    This is a destructive operation -- existing customer data may be
    overwritten.  The form must include a ``confirmed`` field to proceed.
    """
    if not request.form.get("confirmed"):
        flash(
            "CSV reimport is a dangerous operation that can overwrite existing "
            "customer data. Please confirm before proceeding.",
            "warning",
        )
        return redirect(url_for("admin.index"))

    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("No CSV file was uploaded.", "error")
        return redirect(url_for("admin.index"))

    if not csv_file.filename.lower().endswith(".csv"):
        flash("Uploaded file must be a .csv file.", "error")
        return redirect(url_for("admin.index"))

    try:
        from app.models import Customer

        stream = io.TextIOWrapper(csv_file.stream, encoding="utf-8-sig")
        reader = csv.DictReader(stream)

        imported = 0
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue

            customer = Customer.query.filter_by(name=name).first()
            if customer is None:
                customer = Customer(name=name)
                db.session.add(customer)

            customer.address = row.get("address", customer.address)
            customer.city = row.get("city", customer.city)
            customer.phone = row.get("phone", customer.phone)
            customer.notes = row.get("notes", customer.notes)
            imported += 1

        db.session.commit()
        flash(f"Successfully imported/updated {imported} customers.", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Import failed: {exc}", "error")

    return redirect(url_for("admin.index"))
