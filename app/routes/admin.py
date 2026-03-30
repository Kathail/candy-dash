"""Admin routes: user management, audit log, and system operations."""

import csv
import io

from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for, Response
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.helpers import admin_required, audit, sanitize_csv_value
from app.models import User, Customer, Payment, Invoice, Note, RouteStop, ActivityLog, AdminAuditLog, VALID_ROLES
import logging

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@login_required
def before_request():
    """Require login for all admin routes."""
    pass


@bp.route("/")
@admin_required
def index():
    """List all users and recent audit log."""
    users = User.query.order_by(User.username).all()

    filter_action = request.args.get("action", "").strip()
    filter_user = request.args.get("user", "").strip()

    audit_query = AdminAuditLog.query

    if filter_action:
        audit_query = audit_query.filter(AdminAuditLog.action == filter_action)
    if filter_user:
        audit_query = audit_query.join(User).filter(User.username == filter_user)

    audit_logs = (
        audit_query
        .order_by(AdminAuditLog.created_at.desc())
        .limit(200)
        .all()
    )

    # Distinct action types for filter dropdown
    action_types = (
        db.session.query(AdminAuditLog.action)
        .distinct()
        .order_by(AdminAuditLog.action)
        .all()
    )
    action_types = [a[0] for a in action_types]

    return render_template(
        "admin/index.html",
        users=users,
        audit_logs=audit_logs,
        action_types=action_types,
        filter_action=filter_action,
        filter_user=filter_user,
    )


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def create_user():
    """Create a new user."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        role = request.form.get("role", "owner")

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

        if role not in VALID_ROLES:
            flash("Invalid role selected.", "error")
            return render_template("admin/user_form.html", editing=False), 400

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        audit("user_created", f"Created user '{username}' with role '{role}'")
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

        if role not in VALID_ROLES:
            flash("Invalid role selected.", "error")
            return render_template("admin/user_form.html", user=user, editing=True), 400

        # Prevent admins from locking themselves out
        if user.id == current_user.id:
            if not is_active:
                flash("You cannot deactivate your own account.", "error")
                return redirect(url_for("admin.edit_user", id=user.id))
            if role not in ("admin", "owner"):
                flash("You cannot remove your own admin privileges.", "error")
                return redirect(url_for("admin.edit_user", id=user.id))

        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user.id:
            flash("A user with that username already exists.", "error")
            return render_template("admin/user_form.html", user=user, editing=True), 400

        if email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != user.id:
                flash("A user with that email already exists.", "error")
                return render_template("admin/user_form.html", user=user, editing=True), 400

        changes = []
        if user.role != role:
            changes.append(f"role: {user.role} -> {role}")
        if user.is_active != is_active:
            changes.append(f"active: {user.is_active} -> {is_active}")
        if user.username != username:
            changes.append(f"username: {user.username} -> {username}")

        user.username = username
        user.email = email
        user.role = role
        user.is_active = is_active

        if changes:
            audit("user_edited", f"Edited user '{username}': {', '.join(changes)}")

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
    audit("password_reset", f"Reset password for '{user.username}'")
    db.session.commit()

    flash(f"Password for '{user.username}' has been reset.", "success")
    return redirect(url_for("admin.edit_user", id=user.id))


@bp.route("/import-csv", methods=["GET", "POST"])
@admin_required
def import_csv():
    """Import customers or leads from a CSV file."""
    if request.method == "GET":
        return render_template("admin/import_csv.html")

    import re
    from decimal import Decimal, InvalidOperation
    from app.models import Customer

    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("No CSV file was uploaded.", "error")
        return redirect(url_for("admin.import_csv"))

    if not csv_file.filename.lower().endswith(".csv"):
        flash("Uploaded file must be a .csv file.", "error")
        return redirect(url_for("admin.import_csv"))

    import_as = request.form.get("import_as", "customer")
    mode = request.form.get("mode", "skip")

    try:
        stream = io.TextIOWrapper(csv_file.stream, encoding="utf-8-sig")
        reader = csv.DictReader(stream)
        raw_headers = [h.strip() for h in (reader.fieldnames or [])]

        col_map = {}
        for h in raw_headers:
            hl = h.lower()
            if hl in ("name", "business", "store"):
                col_map["name"] = h
            elif hl in ("address", "street", "location"):
                col_map["address"] = h
            elif hl in ("city", "town"):
                col_map["city"] = h
            elif hl in ("phone", "telephone", "tel", "phone number"):
                col_map["phone"] = h
            elif hl in ("notes", "note", "comments", "category"):
                col_map["notes"] = h
            elif hl in ("balance", "owing", "amount"):
                col_map["balance"] = h
            elif hl in ("source", "lead_source", "lead source", "origin"):
                col_map["lead_source"] = h
            elif hl in ("email", "e-mail"):
                col_map["email"] = h

        if "name" not in col_map:
            flash(f"CSV must have a name/Name/business/store column. Found: {', '.join(raw_headers)}", "error")
            return redirect(url_for("admin.import_csv"))

        def normalize(name):
            return re.sub(r"\s+", " ", name.strip().lower())

        def clean_phone(raw):
            raw = (raw or "").strip()
            raw = raw.replace("Phone Number", "").strip()
            cleaned = re.sub(r"[^0-9\-\(\)\+\s]", "", raw)
            return cleaned[:30] if cleaned else None

        def clean_address(raw):
            raw = (raw or "").strip()
            return raw.replace("Get directions", "").strip() or None

        existing = {}
        for c in Customer.query.all():
            existing[normalize(c.name)] = c

        imported = 0
        updated = 0
        skipped = 0
        errors = 0

        for line_num, row in enumerate(reader, start=2):
            raw_name = row.get(col_map["name"], "").strip()
            if not raw_name:
                continue

            norm = normalize(raw_name)
            address = clean_address(row.get(col_map.get("address", ""), ""))
            city_val = row.get(col_map.get("city", ""), "").strip() or None

            if not city_val and address and "," in address:
                parts = [p.strip() for p in address.split(",")]
                if len(parts) >= 2:
                    city_val = parts[1]

            phone = clean_phone(row.get(col_map.get("phone", ""), ""))
            notes = row.get(col_map.get("notes", ""), "").strip() or None
            lead_source = row.get(col_map.get("lead_source", ""), "").strip() or None

            balance = Decimal("0")
            raw_bal = row.get(col_map.get("balance", ""), "").strip()
            if raw_bal:
                try:
                    balance = Decimal(raw_bal.replace(",", "").replace("$", ""))
                except (InvalidOperation, ValueError):
                    pass

            if norm in existing:
                if mode == "update":
                    c = existing[norm]
                    if address: c.address = address
                    if city_val: c.city = city_val
                    if phone: c.phone = phone
                    if notes: c.notes = notes
                    if lead_source: c.lead_source = lead_source
                    if balance is not None: c.balance = balance
                    updated += 1
                else:
                    skipped += 1
                continue

            try:
                status = "lead" if import_as == "lead" else "active"
                customer = Customer(
                    name=raw_name, address=address, city=city_val, phone=phone,
                    notes=notes, balance=balance, status=status,
                    lead_source=lead_source if import_as == "lead" else None,
                )
                db.session.add(customer)
                existing[norm] = customer
                imported += 1
            except Exception:
                errors += 1

        parts = []
        if imported: parts.append(f"{imported} imported")
        if updated: parts.append(f"{updated} updated")
        if skipped: parts.append(f"{skipped} skipped (duplicates)")
        if errors: parts.append(f"{errors} errors")

        summary = f"CSV import ({import_as}): {', '.join(parts)}"
        audit("csv_import", summary)
        db.session.commit()

        flash(f"CSV import complete: {', '.join(parts)}.", "success" if imported or updated else "warning")

    except Exception:
        logging.exception("Operation failed")
        db.session.rollback()
        flash("Import failed. Please check the CSV format and try again.", "error")

    return redirect(url_for("admin.import_csv"))


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

@bp.route("/backups")
@admin_required
def backups():
    """Backup download page."""
    today = date.today()
    customer_count = Customer.query.count()
    payment_count = Payment.query.count()
    stop_count = RouteStop.query.count()
    return render_template(
        "admin/backups.html",
        today=today,
        customer_count=customer_count,
        payment_count=payment_count,
        stop_count=stop_count,
    )


def _csv_response(rows, headers, filename):
    """Build a CSV download response."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([sanitize_csv_value(cell) for cell in row])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/backups/customers.csv")
@admin_required
def backup_customers():
    """Download all customers as CSV."""
    customers = Customer.query.order_by(Customer.name).all()
    rows = [
        [c.id, c.name, c.address or "", c.city or "", c.phone or "",
         str(c.balance), c.status, c.tax_exempt, c.lead_source or "",
         c.created_at, c.updated_at]
        for c in customers
    ]
    return _csv_response(
        rows,
        ["id", "name", "address", "city", "phone", "balance", "status", "tax_exempt", "lead_source", "created_at", "updated_at"],
        f"customers_{date.today().isoformat()}.csv",
    )


@bp.route("/backups/payments.csv")
@admin_required
def backup_payments():
    """Download all payments as CSV."""
    payments = Payment.query.join(Customer).order_by(Payment.payment_date.desc()).all()
    rows = [
        [p.id, p.customer.name, p.customer.city or "",
         str(p.amount), str(p.amount_sold or 0),
         p.payment_date, p.receipt_number,
         str(p.previous_balance), p.notes or "",
         p.recorder.username if p.recorder else ""]
        for p in payments
    ]
    return _csv_response(
        rows,
        ["id", "customer", "city", "amount_paid", "amount_sold", "date", "receipt", "previous_balance", "notes", "recorded_by"],
        f"payments_{date.today().isoformat()}.csv",
    )


@bp.route("/backups/balances.csv")
@admin_required
def backup_balances():
    """Download outstanding balances as CSV."""
    customers = Customer.query.filter(Customer.balance > 0).order_by(Customer.balance.desc()).all()
    rows = [
        [c.name, c.city or "", c.phone or "", str(c.balance), c.tax_exempt]
        for c in customers
    ]
    return _csv_response(
        rows,
        ["name", "city", "phone", "balance", "tax_exempt"],
        f"balances_{date.today().isoformat()}.csv",
    )


@bp.route("/backups/routes.csv")
@admin_required
def backup_routes():
    """Download route history as CSV."""
    stops = RouteStop.query.join(Customer).order_by(RouteStop.route_date.desc()).all()
    rows = [
        [s.route_date, s.customer.name, s.customer.city or "",
         s.sequence, s.completed, s.completed_at, s.notes or ""]
        for s in stops
    ]
    return _csv_response(
        rows,
        ["date", "customer", "city", "sequence", "completed", "completed_at", "notes"],
        f"routes_{date.today().isoformat()}.csv",
    )


@bp.route("/backups/full.csv")
@admin_required
def backup_full():
    """Download everything in one combined CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== CUSTOMERS ==="])
    writer.writerow(["id", "name", "address", "city", "phone", "balance", "status", "tax_exempt"])
    for c in Customer.query.order_by(Customer.name).all():
        writer.writerow([c.id, c.name, c.address or "", c.city or "", c.phone or "", str(c.balance), c.status, c.tax_exempt])

    writer.writerow([])
    writer.writerow(["=== PAYMENTS ==="])
    writer.writerow(["id", "customer", "city", "amount_paid", "amount_sold", "date", "receipt", "previous_balance", "notes"])
    for p in Payment.query.join(Customer).order_by(Payment.payment_date.desc()).all():
        writer.writerow([p.id, p.customer.name, p.customer.city or "", str(p.amount), str(p.amount_sold or 0), p.payment_date, p.receipt_number, str(p.previous_balance), p.notes or ""])

    writer.writerow([])
    writer.writerow(["=== ROUTE HISTORY ==="])
    writer.writerow(["date", "customer", "city", "completed", "completed_at"])
    for s in RouteStop.query.join(Customer).order_by(RouteStop.route_date.desc()).all():
        writer.writerow([s.route_date, s.customer.name, s.customer.city or "", s.completed, s.completed_at])

    writer.writerow([])
    writer.writerow(["=== INVOICES ==="])
    writer.writerow(["id", "customer", "city", "amount", "invoice_number", "date", "description", "status"])
    for inv in Invoice.query.join(Customer).order_by(Invoice.invoice_date.desc()).all():
        writer.writerow([inv.id, inv.customer.name, inv.customer.city or "", str(inv.amount), inv.invoice_number or "", inv.invoice_date, inv.description or "", inv.status])

    writer.writerow([])
    writer.writerow(["=== NOTES ==="])
    writer.writerow(["customer", "note", "author", "date"])
    for n in Note.query.join(Customer).order_by(Note.created_at.desc()).all():
        writer.writerow([n.customer.name, n.text, n.user.username if n.user else "", n.created_at])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=candy_dash_backup_{date.today().isoformat()}.csv"},
    )


@bp.route("/backups/invoices.csv")
@admin_required
def backup_invoices():
    """Download all invoices as CSV."""
    invoices = Invoice.query.join(Customer).order_by(Invoice.invoice_date.desc()).all()
    rows = [
        [inv.id, inv.customer.name, inv.customer.city or "",
         str(inv.amount), inv.invoice_number or "",
         inv.invoice_date, inv.description or "", inv.status]
        for inv in invoices
    ]
    return _csv_response(
        rows,
        ["id", "customer", "city", "amount", "invoice_number", "date", "description", "status"],
        f"invoices_{date.today().isoformat()}.csv",
    )


@bp.route("/backups/notes.csv")
@admin_required
def backup_notes():
    """Download all notes as CSV."""
    notes = Note.query.join(Customer).order_by(Note.created_at.desc()).all()
    rows = [
        [n.customer.name, n.text, n.user.username if n.user else "", n.created_at]
        for n in notes
    ]
    return _csv_response(
        rows,
        ["customer", "note", "author", "date"],
        f"notes_{date.today().isoformat()}.csv",
    )
