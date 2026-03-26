"""Customers blueprint – CRUD, payments, notes, status."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from app import db
from app.models import Customer, Payment, ActivityLog, RouteStop
from app.helpers import admin_required, generate_receipt_number

bp = Blueprint("customers", __name__, url_prefix="/customers")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    """Paginated, searchable, filterable customer list."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    city_filter = request.args.get("city", "").strip()
    sort = request.args.get("sort", "name")
    direction = request.args.get("dir", "asc")

    query = Customer.query

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

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Distinct cities for filter dropdown
    cities = (
        db.session.query(Customer.city)
        .filter(Customer.city.isnot(None), Customer.city != "")
        .distinct()
        .order_by(Customer.city)
        .all()
    )
    cities = [c[0] for c in cities]

    # HTMX partial response
    if request.headers.get("HX-Request"):
        return render_template(
            "partials/customer_rows.html",
            pagination=pagination,
        )

    return render_template(
        "customers.html",
        pagination=pagination,
        q=q,
        status_filter=status_filter,
        city_filter=city_filter,
        sort=sort,
        direction=direction,
        cities=cities,
    )


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

        customer = Customer(
            name=name,
            address=request.form.get("address", "").strip(),
            city=request.form.get("city", "").strip(),
            phone=request.form.get("phone", "").strip(),
            notes=request.form.get("notes", "").strip(),
            balance=Decimal(request.form.get("balance", "0") or "0"),
            status=request.form.get("status", "active"),
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

        customer.name = name
        customer.address = request.form.get("address", "").strip()
        customer.city = request.form.get("city", "").strip()
        customer.phone = request.form.get("phone", "").strip()
        customer.notes = request.form.get("notes", "").strip()
        customer.balance = Decimal(request.form.get("balance", "0") or "0")
        customer.status = request.form.get("status", "active")
        customer.tax_exempt = bool(request.form.get("tax_exempt"))
        customer.lead_source = request.form.get("lead_source", "").strip() or None

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="customer_edited",
            description=f"Customer '{customer.name}' updated.",
        ))
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
    """Record a payment against the customer balance – fully atomic."""
    customer = Customer.query.get_or_404(id)

    raw_amount = request.form.get("amount", "").strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        flash("Invalid payment amount.", "error")
        return redirect(url_for("customers.profile", id=customer.id))

    if amount <= 0:
        flash("Payment amount must be greater than zero.", "error")
        return redirect(url_for("customers.profile", id=customer.id))

    notes = request.form.get("notes", "").strip() or None

    try:
        # Snapshot current balance
        previous_balance = customer.balance

        receipt_number = generate_receipt_number()

        payment = Payment(
            customer_id=customer.id,
            amount=amount,
            receipt_number=receipt_number,
            previous_balance=previous_balance,
            notes=notes,
            recorded_by=current_user.id,
        )
        db.session.add(payment)

        customer.balance = previous_balance - amount

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_recorded",
            description=(
                f"Payment of ${amount:,.2f} recorded. "
                f"Receipt #{receipt_number}. "
                f"Balance: ${previous_balance:,.2f} → ${customer.balance:,.2f}."
            ),
        ))

        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("An error occurred while recording the payment.", "error")
        return redirect(url_for("customers.profile", id=customer.id))

    flash(
        f"Payment of ${amount:,.2f} recorded successfully. Receipt #{receipt_number}.",
        "success",
    )
    return redirect(url_for("customers.profile", id=customer.id))


# ---------------------------------------------------------------------------
# Delete payment (admin only, ATOMIC)
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/delete-payment/<int:payment_id>", methods=["POST"])
@login_required
@admin_required
def delete_payment(id, payment_id):
    """Admin-only: reverse and delete a payment."""
    customer = Customer.query.get_or_404(id)
    payment = Payment.query.get_or_404(payment_id)

    if payment.customer_id != customer.id:
        abort(404)

    try:
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
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("An error occurred while deleting the payment.", "error")
        return redirect(url_for("customers.profile", id=customer.id))

    flash(f"Payment #{payment.receipt_number} deleted and balance restored.", "success")
    return redirect(url_for("customers.profile", id=customer.id))


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
    db.session.commit()

    flash(f"Customer status changed to {customer.status}.", "success")
    return redirect(url_for("customers.profile", id=customer.id))
