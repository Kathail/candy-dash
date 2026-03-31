"""Customers blueprint – CRUD, payments, notes, status."""

import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, Response, send_file,
)
from flask_login import login_required, current_user

from app import db, limiter
from app.models import Customer, Payment, Invoice, InvoiceItem, Note, ActivityLog, RouteStop, VALID_CUSTOMER_STATUSES
from app.helpers import admin_required, staff_required, generate_receipt_number, generate_receipt_pdf, audit, safe_redirect
import logging

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

    # Only show customers (active/inactive), not leads or deleted — leads have their own page
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

    invoices = (
        Invoice.query
        .filter_by(customer_id=customer.id)
        .order_by(Invoice.invoice_date.desc())
        .all()
    )

    notes = (
        Note.query
        .filter_by(customer_id=customer.id)
        .order_by(Note.created_at.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "customer_profile.html",
        customer=customer,
        payments=payments,
        activity=activity,
        route_history=route_history,
        invoices=invoices,
        notes=notes,
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
@limiter.limit("30/minute")
def record_payment(id):
    """Record a sale and/or payment for a customer – fully atomic.

    Accepts amount_sold (increases balance) and amount_paid (decreases balance).
    Falls back to legacy 'amount' field as amount_paid for backwards compat.
    """
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    redirect_to = safe_redirect(request.form.get("next")) or url_for("customers.profile", id=id)

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
    payment_type = request.form.get("payment_type", "cash").strip() or "cash"

    try:
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()
        previous_balance = customer.balance

        # Apply sale (increases balance) then payment (decreases balance)
        new_balance = previous_balance + amount_sold - amount_paid
        if new_balance < 0:
            new_balance = Decimal("0")
        customer.balance = new_balance

        receipt_number = generate_receipt_number()

        # Record the payment entry
        payment = Payment(
            customer_id=customer.id,
            amount=amount_paid,
            amount_sold=amount_sold,
            payment_type=payment_type,
            receipt_number=receipt_number,
            previous_balance=previous_balance,
            notes=notes,
            recorded_by=current_user.id,
        )
        db.session.add(payment)

        # Auto-create invoice when a sale is recorded
        if amount_sold > 0:
            from datetime import date as date_type
            invoice = Invoice(
                customer_id=customer.id,
                invoice_number=receipt_number,
                amount=amount_sold,
                invoice_date=date_type.today(),
                description=notes,
                payment_type=payment_type,
                status="paid" if amount_paid >= amount_sold else "unpaid",
                created_by=current_user.id,
            )
            db.session.add(invoice)

        # Mark unpaid invoices as paid if balance is now zero
        if new_balance == 0 and amount_paid > 0:
            unpaid_invoices = Invoice.query.filter_by(
                customer_id=customer.id, status="unpaid"
            ).all()
            for inv in unpaid_invoices:
                inv.status = "paid"
                inv.payment_type = payment_type

        # Build description
        parts = []
        if amount_sold > 0:
            parts.append(f"Sold ${amount_sold:,.2f}")
        if amount_paid > 0:
            parts.append(f"Paid ${amount_paid:,.2f}")
        desc = ". ".join(parts) + f". Invoice #{receipt_number}. Balance: ${previous_balance:,.2f} → ${new_balance:,.2f}."

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_recorded",
            description=desc,
        ))
        audit("payment_recorded", f"{desc} Customer: {customer.name}")

        db.session.commit()
    except Exception:
        logging.exception("Transaction failed")
        db.session.rollback()
        return _error("An error occurred while recording the transaction.")

    if is_fetch:
        return jsonify({"ok": True, "receipt_number": receipt_number, "new_balance": float(new_balance)})

    if amount_sold > 0:
        flash(f"Transaction recorded. Invoice #{receipt_number}. Sale ${amount_sold:,.2f}.", "success")
    else:
        flash(f"Transaction recorded. Invoice #{receipt_number}.", "success")
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
        # Reverse both legs: undo the sale (amount_sold) and undo the payment (amount)
        customer.balance = customer.balance - (payment.amount_sold or Decimal("0")) + payment.amount

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_deleted",
            description=(
                f"Payment #{payment.receipt_number} of ${payment.amount:,.2f} deleted"
                f" (sold: ${(payment.amount_sold or Decimal('0')):,.2f}). "
                f"Balance restored to ${customer.balance:,.2f}."
            ),
        ))

        db.session.delete(payment)
        audit("payment_deleted", f"Deleted payment #{payment.receipt_number} (${payment.amount:,.2f}) for '{customer.name}'. Balance restored to ${customer.balance:,.2f}.")
        db.session.commit()
    except Exception:
        logging.exception("Operation failed")
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


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@staff_required
def delete_customer(id):
    """Soft-delete a customer by setting status to 'deleted'."""
    customer = Customer.query.get_or_404(id)
    old_status = customer.status

    customer.status = "deleted"

    db.session.add(ActivityLog(
        customer_id=customer.id,
        user_id=current_user.id,
        action="status_changed",
        description=f"Customer deleted (was {old_status}).",
    ))
    audit("customer_deleted", f"Deleted customer '{customer.name}' (was {old_status})")
    db.session.commit()

    flash(f"Customer '{customer.name}' deleted.", "success")
    return redirect(url_for("customers.index"))


# ---------------------------------------------------------------------------
# Toggle tax exempt
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/toggle-tax-exempt", methods=["POST"])
@login_required
def toggle_tax_exempt(id):
    """Toggle customer tax exempt status."""
    customer = Customer.query.get_or_404(id)
    customer.tax_exempt = not customer.tax_exempt

    db.session.add(ActivityLog(
        customer_id=customer.id,
        user_id=current_user.id,
        action="tax_exempt_changed",
        description=f"Tax exempt {'enabled' if customer.tax_exempt else 'disabled'}.",
    ))
    audit("tax_exempt_changed", f"'{customer.name}' tax exempt: {customer.tax_exempt}")
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "tax_exempt": customer.tax_exempt})

    flash(f"Tax exempt {'enabled' if customer.tax_exempt else 'disabled'} for {customer.name}.", "success")
    return redirect(url_for("customers.profile", id=customer.id))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/invoices/add", methods=["POST"])
@login_required
def add_invoice(id):
    """Add an invoice to a customer."""
    customer = Customer.query.get_or_404(id)

    try:
        amount = Decimal(request.form.get("amount", "0") or "0")
    except (InvalidOperation, ValueError):
        flash("Invalid amount.", "error")
        return redirect(url_for("customers.profile", id=id))

    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for("customers.profile", id=id))

    invoice_date_str = request.form.get("invoice_date", "")
    try:
        from datetime import date as date_type
        invoice_date = date_type.fromisoformat(invoice_date_str) if invoice_date_str else date_type.today()
    except ValueError:
        invoice_date = date_type.today()

    invoice = Invoice(
        customer_id=customer.id,
        invoice_number=request.form.get("invoice_number", "").strip() or None,
        amount=amount,
        invoice_date=invoice_date,
        description=request.form.get("description", "").strip() or None,
        payment_type=request.form.get("payment_type", "").strip() or None,
        status="unpaid",
        created_by=current_user.id,
    )

    # Parse line items
    item_count = int(request.form.get("item_count", 0) or 0)
    for i in range(item_count):
        item_qty = Decimal(request.form.get(f"item_qty_{i}", "0") or "0")
        item_price = Decimal(request.form.get(f"item_price_{i}", "0") or "0")
        item_amount = item_qty * item_price
        if item_amount > 0:
            invoice.items.append(InvoiceItem(
                item_number=request.form.get(f"item_number_{i}", "").strip() or None,
                description=request.form.get(f"item_desc_{i}", "").strip() or None,
                quantity=item_qty,
                weight=request.form.get(f"item_weight_{i}", "").strip() or None,
                unit_price=item_price,
                amount=item_amount,
            ))

    try:
        db.session.add(invoice)

        # Lock the customer row for safe balance update
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()

        # Add the invoice amount to customer balance
        customer.balance += amount

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="invoice_added",
            description=f"Invoice ${amount:,.2f} added. Balance: ${customer.balance:,.2f}.",
        ))
        audit("invoice_added", f"Invoice ${amount:,.2f} for '{customer.name}'")
        db.session.commit()
    except Exception:
        logging.exception("Invoice creation failed")
        db.session.rollback()
        flash("An error occurred while adding the invoice.", "error")
        return redirect(url_for("customers.profile", id=id))

    flash(f"Invoice for ${amount:,.2f} added.", "success")
    return redirect(url_for("customers.profile", id=id))


@bp.route("/<int:id>/invoices/<int:invoice_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_invoice(id, invoice_id):
    """Delete an invoice and reverse the balance change."""
    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.customer_id != id:
        abort(404)

    try:
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()

        # Only reverse balance if invoice is unpaid (paid invoices were already
        # settled via a payment record that reduced the balance separately).
        if invoice.status != "paid":
            customer.balance = max(customer.balance - invoice.amount, Decimal("0"))

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="invoice_deleted",
            description=f"Invoice #{invoice.invoice_number or invoice.id} (${invoice.amount:,.2f}, {invoice.status}) deleted. Balance: ${customer.balance:,.2f}.",
        ))

        db.session.delete(invoice)
        audit("invoice_deleted", f"Deleted invoice ${invoice.amount:,.2f} ({invoice.status}) for '{customer.name}'")
        db.session.commit()
    except Exception:
        logging.exception("Invoice deletion failed")
        db.session.rollback()
        flash("Failed to delete invoice.", "error")
        return redirect(url_for("customers.profile", id=id))

    flash("Invoice deleted and balance adjusted.", "success")
    return redirect(url_for("customers.profile", id=id))


@bp.route("/<int:id>/invoices/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required
def mark_invoice_paid(id, invoice_id):
    """Mark an invoice as paid and reduce customer balance."""
    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.customer_id != id:
        abort(404)
    if invoice.status == "paid":
        flash("Invoice already paid.", "warning")
        return redirect(url_for("customers.profile", id=id))

    try:
        customer = db.session.query(Customer).filter_by(id=id).with_for_update().one()
        previous_balance = customer.balance
        customer.balance = max(previous_balance - invoice.amount, Decimal("0"))
        pay_type = request.form.get("payment_type", "cash")
        invoice.status = "paid"
        invoice.payment_type = pay_type

        # Record as a payment
        receipt_number = generate_receipt_number()
        payment = Payment(
            customer_id=customer.id,
            amount=invoice.amount,
            amount_sold=Decimal("0"),
            payment_type=pay_type,
            receipt_number=receipt_number,
            previous_balance=previous_balance,
            notes=f"Invoice #{invoice.invoice_number or invoice.id} paid",
            recorded_by=current_user.id,
        )
        db.session.add(payment)

        db.session.add(ActivityLog(
            customer_id=customer.id,
            user_id=current_user.id,
            action="payment_recorded",
            description=f"Invoice #{invoice.invoice_number or invoice.id} paid. ${invoice.amount:,.2f}. Balance: ${previous_balance:,.2f} → ${customer.balance:,.2f}.",
        ))
        audit("invoice_paid", f"Invoice #{invoice.invoice_number or invoice.id} (${invoice.amount:,.2f}) for '{customer.name}'")
        db.session.commit()
    except Exception:
        logging.exception("Invoice payment failed")
        db.session.rollback()
        flash("Failed to process payment.", "error")
        return redirect(url_for("customers.profile", id=id))

    flash(f"Invoice paid. Invoice #{receipt_number}.", "success")
    return redirect(url_for("customers.profile", id=id))


# ---------------------------------------------------------------------------
# Notes (individual entries)
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/notes/add", methods=["POST"])
@login_required
def add_note_entry(id):
    """Add a note entry to a customer."""
    customer = Customer.query.get_or_404(id)
    text = request.form.get("text", "").strip()

    if not text:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("customers.profile", id=id))

    note = Note(
        customer_id=customer.id,
        user_id=current_user.id,
        text=text,
    )
    db.session.add(note)

    db.session.add(ActivityLog(
        customer_id=customer.id,
        user_id=current_user.id,
        action="note_added",
        description=text,
    ))
    db.session.commit()

    flash("Note added.", "success")
    return redirect(url_for("customers.profile", id=id))


@bp.route("/<int:id>/notes/<int:note_id>/delete", methods=["POST"])
@login_required
@staff_required
def delete_note(id, note_id):
    """Delete a note entry."""
    note = Note.query.get_or_404(note_id)
    if note.customer_id != id:
        abort(404)
    db.session.delete(note)
    db.session.commit()
    flash("Note deleted.", "success")
    return redirect(url_for("customers.profile", id=id))


# ---------------------------------------------------------------------------
# Invoice PDF
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/invoices/<int:invoice_id>/pdf")
@login_required
def invoice_pdf(id, invoice_id):
    """Generate a PDF invoice with company logo."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    import os

    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.customer_id != id:
        abort(404)
    customer = Customer.query.get_or_404(id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Logo
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "img", "logo.png")
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=1.2 * inch, height=1.2 * inch)
            elements.append(logo)
            elements.append(Spacer(1, 12))
        except Exception:
            pass

    # Title
    title_style = ParagraphStyle("InvTitle", parent=styles["Title"], fontSize=20, spaceAfter=6)
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Spacer(1, 12))

    # Invoice details
    detail_style = ParagraphStyle("Detail", parent=styles["Normal"], fontSize=11, spaceAfter=4)
    normal_center = ParagraphStyle("NormalCenter", parent=styles["Normal"], alignment=1)
    if invoice.invoice_number:
        elements.append(Paragraph(f"<b>Invoice #:</b> {invoice.invoice_number}", detail_style))
    elements.append(Paragraph(f"<b>Date:</b> {invoice.invoice_date}", detail_style))
    elements.append(Paragraph(f"<b>Status:</b> {invoice.status.upper()}", detail_style))
    if invoice.payment_type:
        elements.append(Paragraph(f"<b>Payment Type:</b> {invoice.payment_type.capitalize()}", detail_style))
    elements.append(Spacer(1, 16))

    # Customer info
    elements.append(Paragraph("<b>Bill To:</b>", detail_style))
    elements.append(Paragraph(customer.name, detail_style))
    if customer.address:
        elements.append(Paragraph(customer.address, detail_style))
    if customer.city:
        elements.append(Paragraph(customer.city, detail_style))
    if customer.phone:
        elements.append(Paragraph(customer.phone, detail_style))
    elements.append(Spacer(1, 20))

    # Line items table
    from decimal import Decimal as Dec
    line_items = invoice.items or []

    if line_items:
        data = [["Item #", "Description", "Qty", "Weight", "Unit Price", "Amount"]]
        subtotal = Dec("0")
        for item in line_items:
            data.append([
                item.item_number or "",
                item.description or "",
                f"{item.quantity:g}" if item.quantity else "",
                item.weight or "",
                f"${item.unit_price:,.2f}" if item.unit_price else "",
                f"${item.amount:,.2f}",
            ])
            subtotal += item.amount or Dec("0")

        total = subtotal

        data.append(["", "", "", "", "Total:", f"${total:,.2f}"])

        t = Table(data, colWidths=[0.8 * inch, 1.8 * inch, 0.6 * inch, 0.8 * inch, 1 * inch, 1 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (-2, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#4b5563")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#4b5563")),
            ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
    else:
        # Fallback: single-line invoice (e.g. from quick sale)
        total = invoice.amount

        data = [
            ["Description", "Amount"],
            [invoice.description or "Goods/Services", f"${invoice.amount:,.2f}"],
            ["", ""],
            ["Total", f"${total:,.2f}"],
        ]
        t = Table(data, colWidths=[4 * inch, 2 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#4b5563")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#4b5563")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))

    elements.append(t)
    elements.append(Spacer(1, 0.5 * inch))

    if invoice.status == "unpaid":
        elements.append(Paragraph(
            f"Balance owing: ${total:,.2f}. Please remit payment at your earliest convenience.",
            normal_center,
        ))
    else:
        elements.append(Paragraph("Thank you for your payment!", normal_center))

    doc.build(elements)
    buf.seek(0)

    import re
    safe_name = re.sub(r'[^\w-]', '_', customer.name)
    filename = f"invoice_{invoice.invoice_number or invoice.id}_{safe_name}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=filename)


# ---------------------------------------------------------------------------
# Payment receipt PDF
# ---------------------------------------------------------------------------

@bp.route("/<int:id>/payments/<int:payment_id>/pdf")
@login_required
def payment_receipt_pdf(id, payment_id):
    """Generate a PDF receipt for a single payment."""
    payment = Payment.query.get_or_404(payment_id)
    if payment.customer_id != id:
        abort(404)
    customer = Customer.query.get_or_404(id)

    pdf_bytes = generate_receipt_pdf(payment, customer)
    buf = io.BytesIO(pdf_bytes)

    import re
    safe_name = re.sub(r'[^\w-]', '_', customer.name)
    filename = f"{payment.receipt_number}_{safe_name}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=filename)
