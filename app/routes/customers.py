"""Customers blueprint – CRUD, payments, notes, status."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify,
)
from flask_login import login_required, current_user

from app import db
from app.models import Customer, Payment, ActivityLog, RouteStop, VALID_CUSTOMER_STATUSES
from app.helpers import admin_required, generate_receipt_number, audit

bp = Blueprint("customers", __name__, url_prefix="/customers")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    """Paginated, searchable, filterable customer list."""
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    city_filter = request.args.get("city", "").strip()
    sort_param = request.args.get("sort", "name")
    # Support combined sort values like "balance_desc" or separate sort+dir
    direction = request.args.get("dir", "asc")
    if sort_param.endswith("_desc"):
        sort = sort_param.rsplit("_", 1)[0]
        direction = "desc"
    elif sort_param.endswith("_asc"):
        sort = sort_param.rsplit("_", 1)[0]
        direction = "asc"
    else:
        sort = sort_param

    # Only show customers (active/inactive), not leads — leads have their own page
    query = Customer.query.filter(Customer.status.in_(("active", "inactive")))

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Customer.address.ilike(like),
            )
        )

    if status_filter:
        query = query.filter(Customer.status == status_filter)

    if city_filter:
        query = query.filter(Customer.city == city_filter)

    # Sorting
    sort_col = {
        "name": Customer.name,
        "balance": Customer.balance,
        "city": Customer.city,
    }.get(sort, Customer.name)

    if direction == "desc":
        sort_col = sort_col.desc()

    query = query.order_by(sort_col)

    # Distinct cities for filter dropdown
    cities = (
        db.session.query(Customer.city)
        .filter(Customer.city.isnot(None), Customer.city != "")
        .distinct()
        .order_by(Customer.city)
        .all()
    )
    cities = [c[0] for c in cities]

    customers = query.all()
    customer_ids = [c.id for c in customers]

    # Last completed visit per customer
    from sqlalchemy import func
    from datetime import date
    last_visits = {}
    if customer_ids:
        rows = (
            db.session.query(
                RouteStop.customer_id,
                func.max(RouteStop.route_date).label("last_date"),
            )
            .filter(
                RouteStop.customer_id.in_(customer_ids),
                RouteStop.completed.is_(True),
            )
            .group_by(RouteStop.customer_id)
            .all()
        )
        last_visits = {r.customer_id: r.last_date for r in rows}

    # Last note per customer
    last_notes = {}
    if customer_ids:
        rows = (
            db.session.query(
                ActivityLog.customer_id,
                ActivityLog.description,
                ActivityLog.created_at,
            )
            .filter(
                ActivityLog.customer_id.in_(customer_ids),
                ActivityLog.action == "note_added",
            )
            .order_by(ActivityLog.customer_id, ActivityLog.created_at.desc())
            .all()
        )
        for r in rows:
            if r.customer_id not in last_notes:
                last_notes[r.customer_id] = r.description

    # Group by city for the default view
    from collections import OrderedDict
    grouped = OrderedDict()
    for c in customers:
        city = c.city or "No City"
        grouped.setdefault(city, []).append(c)

    today = date.today()
    tpl_ctx = dict(
        customers=customers,
        grouped=grouped,
        last_visits=last_visits,
        last_notes=last_notes,
        q=q,
        status_filter=status_filter,
        city_filter=city_filter,
        sort=sort,
        direction=direction,
        cities=cities,
        today=today,
    )

    return render_template("customers.html", **tpl_ctx)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@bp.route("/<int:id>")
@login_required
def profile(id):
    """Customer detail with payment history, activity, and route history."""
    customer = Customer.query.get_or_404(id)

    payments = (
        Payment.query
        .filter_by(customer_id=customer.id)
        .order_by(Payment.payment_date.desc())
        .limit(200)
        .all()
    )

    activity = (
        ActivityLog.query
        .filter_by(customer_id=customer.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
        .all()
    )

    route_history = (
        RouteStop.query
        .filter_by(customer_id=customer.id)
        .order_by(RouteStop.route_date.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "customer_profile.html",
        customer=customer,
        payments=payments,
        activity=activity,
        route_history=route_history,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Create a new customer."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Customer name is required.", "error")
            return render_template("customer_form.html", customer=None)

        status = request.form.get("status", "active")
        if status not in VALID_CUSTOMER_STATUSES:
            flash("Invalid status.", "error")
            return render_template("customer_form.html", customer=None), 400

        try:
            balance = Decimal(request.form.get("balance", "0") or "0")
        except (InvalidOperation, ValueError):
            flash("Invalid balance amount.", "error")
            return render_template("customer_form.html", customer=None), 400

        customer = Customer(
            name=name,
            address=request.form.get("address", "").strip(),
            city=request.form.get("city", "").strip(),
            phone=request.form.get("phone", "").strip(),
            notes=request.form.get("notes", "").strip(),
            balance=balance,
            status=status,
            tax_exempt=bool(request.form.get("tax_exempt")),
            lead_source=request.form.get("lead_source", "").strip() or None,
        )
        db.session.add(customer)
        db.session.flush()

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="customer_created",
            description=f"Customer '{customer.name}' created.",
        ))
        audit("customer_created", f"Created customer '{customer.name}' (status: {status})")
        db.session.commit()

        flash(f"Customer '{customer.name}' created.", "success")
        return redirect(url_for("customers.profile", id=customer.id))

    return render_template("customer_form.html", customer=None)


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit(id):
    """Edit an existing customer."""
    customer = Customer.query.get_or_404(id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Customer name is required.", "error")
            return render_template("customer_form.html", customer=customer)

        status = request.form.get("status", "active")
        if status not in VALID_CUSTOMER_STATUSES:
            flash("Invalid status.", "error")
            return render_template("customer_form.html", customer=customer), 400

        try:
            balance = Decimal(request.form.get("balance", "0") or "0")
        except (InvalidOperation, ValueError):
            flash("Invalid balance amount.", "error")
            return render_template("customer_form.html", customer=customer), 400

        customer.name = name
        customer.address = request.form.get("address", "").strip()
        customer.city = request.form.get("city", "").strip()
        customer.phone = request.form.get("phone", "").strip()
        customer.notes = request.form.get("notes", "").strip()
        customer.balance = balance
        customer.status = status
        customer.tax_exempt = bool(request.form.get("tax_exempt"))
        customer.lead_source = request.form.get("lead_source", "").strip() or None

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="customer_edited",
            description=f"Customer '{customer.name}' updated.",
        ))
        audit("customer_edited", f"Edited customer '{customer.name}'")
        db.session.commit()

        flash(f"Customer '{customer.name}' updated.", "success")
        return redirect(url_for("customers.profile", id=customer.id))

    return render_template("customer_form.html", customer=customer)


# ---------------------------------------------------------------------------
# Record payment (ATOMIC)
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/payment", methods=["POST"])
@login_required
def record_payment(id):
    """Record a sale and/or payment for a customer – fully atomic.

    Accepts amount_sold (increases balance) and amount_paid (decreases balance).
    Falls back to legacy 'amount' field as amount_paid for backwards compat.
    """
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    redirect_to = request.form.get("next") or url_for("customers.profile", id=id)

    def _error(msg):
        if is_fetch:
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "error")
        return redirect(redirect_to)

    # Parse amounts
    raw_sold = request.form.get("amount_sold", "").strip()
    raw_paid = request.form.get("amount_paid", "").strip() or request.form.get("amount", "").strip()

    try:
        amount_sold = Decimal(raw_sold) if raw_sold else Decimal("0")
    except (InvalidOperation, ValueError):
        return _error("Invalid sold amount.")

    try:
        amount_paid = Decimal(raw_paid) if raw_paid else Decimal("0")
    except (InvalidOperation, ValueError):
        return _error("Invalid paid amount.")

    if amount_sold < 0 or amount_paid < 0:
        return _error("Amounts cannot be negative.")

    if amount_sold == 0 and amount_paid == 0:
        return _error("Enter an amount sold or paid.")

    notes = request.form.get("notes", "").strip() or None

    try:
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()
        previous_balance = customer.balance

        # Apply sale (increases balance) then payment (decreases balance)
        new_balance = previous_balance + amount_sold - amount_paid
        customer.balance = new_balance

        receipt_number = generate_receipt_number()

        # Record the payment entry (amount = net paid)
        payment = Payment(
            customer_id=customer.id,
            amount=amount_paid,
            receipt_number=receipt_number,
            previous_balance=previous_balance,
            notes=notes,
            recorded_by=current_user.id,
        )
        db.session.add(payment)

        # Build description
        parts = []
        if amount_sold > 0:
            parts.append(f"Sold ${amount_sold:,.2f}")
        if amount_paid > 0:
            parts.append(f"Paid ${amount_paid:,.2f}")
        desc = ". ".join(parts) + f". Receipt #{receipt_number}. Balance: ${previous_balance:,.2f} → ${new_balance:,.2f}."

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_recorded",
            description=desc,
        ))
        audit("payment_recorded", f"{desc} Customer: {customer.name}")

        db.session.commit()
    except Exception:
        db.session.rollback()
        return _error("An error occurred while recording the transaction.")

    if is_fetch:
        return jsonify({"ok": True, "receipt_number": receipt_number, "new_balance": float(new_balance)})

    flash(f"Transaction recorded. Receipt #{receipt_number}.", "success")
    return redirect(redirect_to)


# ---------------------------------------------------------------------------
# Delete payment (admin only, ATOMIC)
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/delete-payment/<int:payment_id>", methods=["POST"])
@login_required
@admin_required
def delete_payment(id, payment_id):
    """Admin-only: reverse and delete a payment."""
    payment = Payment.query.get_or_404(payment_id)

    if payment.customer_id != id:
        abort(404)

    try:
        # Lock the customer row to prevent concurrent balance updates
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()
        customer.balance = customer.balance + payment.amount

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_deleted",
            description=(
                f"Payment #{payment.receipt_number} of ${payment.amount:,.2f} deleted. "
                f"Balance restored to ${customer.balance:,.2f}."
            ),
        ))

        db.session.delete(payment)
        audit("payment_deleted", f"Deleted payment #{payment.receipt_number} (${payment.amount:,.2f}) for '{customer.name}'. Balance restored to ${customer.balance:,.2f}.")
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("An error occurred while deleting the payment.", "error")
        return redirect(url_for("customers.profile", id=id))

    flash(f"Payment #{payment.receipt_number} deleted and balance restored.", "success")
    return redirect(url_for("customers.profile", id=id))


# ---------------------------------------------------------------------------
# Add note
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/add-note", methods=["POST"])
@login_required
def add_note(id):
    """Append a note to the customer and log the activity."""
    customer = Customer.query.get_or_404(id)
    note = request.form.get("note", "").strip()

    if not note:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("customers.profile", id=customer.id))

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    separator = "\n---\n" if customer.notes else ""
    customer.notes = (customer.notes or "") + f"{separator}[{timestamp}] {note}"

    db.session.add(ActivityLog(
        customer_id=customer.id,
        user_id=current_user.id,
        action="note_added",
        description=note,
    ))
    audit("note_added", f"Note added to '{customer.name}'")
    db.session.commit()

    flash("Note added.", "success")
    return redirect(url_for("customers.profile", id=customer.id))


# ---------------------------------------------------------------------------
# Toggle status
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/toggle-status", methods=["POST"])
@login_required
def toggle_status(id):
    """Toggle customer between active and inactive."""
    customer = Customer.query.get_or_404(id)
    old_status = customer.status
    customer.status = "inactive" if old_status == "active" else "active"

    db.session.add(ActivityLog(
        customer_id=customer.id,
        user_id=current_user.id,
        action="status_changed",
        description=f"Status changed from {old_status} to {customer.status}.",
    ))
    audit("status_changed", f"'{customer.name}' status: {old_status} → {customer.status}")
    db.session.commit()

    flash(f"Customer status changed to {customer.status}.", "success")
    return redirect(url_for("customers.profile", id=customer.id))
