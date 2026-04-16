"""Route blueprint – daily route execution, completion tracking, receipts."""

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify,
    make_response,
)
from flask_login import login_required, current_user
from sqlalchemy import func

from sqlalchemy.orm import joinedload

from app import db
from app.models import Customer, Invoice, RouteStop, Payment, ActivityLog, VALID_PAYMENT_TYPES
from app.helpers import generate_receipt_pdf, generate_receipt_number, audit, staff_required
import logging

bp = Blueprint("route", __name__, url_prefix="/route")


@bp.route("/")
@login_required
def index():
    """Show today's route (or a specific date) ordered by city then sequence."""
    date_param = request.args.get("date", "")
    if date_param:
        try:
            route_date = date.fromisoformat(date_param)
        except ValueError:
            route_date = date.today()
    else:
        route_date = date.today()

    stops = (
        RouteStop.query
        .options(joinedload(RouteStop.customer))
        .join(Customer)
        .filter(RouteStop.route_date == route_date)
        .order_by(Customer.city, RouteStop.sequence)
        .all()
    )

    # Collection target: total outstanding balance across today's stop customers
    customer_ids = [s.customer_id for s in stops]
    collection_target = Decimal("0")
    if customer_ids:
        collection_target = db.session.query(
            func.coalesce(func.sum(Customer.balance), Decimal("0"))
        ).filter(
            Customer.id.in_(customer_ids),
            Customer.balance > 0,
        ).scalar() or Decimal("0")

    # Today's collections so far
    day_start = datetime(route_date.year, route_date.month, route_date.day, tzinfo=timezone.utc)
    day_end = datetime(route_date.year, route_date.month, route_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    collected_today = db.session.query(
        func.coalesce(func.sum(Payment.amount), Decimal("0"))
    ).filter(
        Payment.payment_date >= day_start,
        Payment.payment_date <= day_end,
    ).scalar() or Decimal("0")

    # Today's actual sales (goods delivered)
    sales_today = db.session.query(
        func.coalesce(func.sum(Payment.amount_sold), Decimal("0"))
    ).filter(
        Payment.payment_date >= day_start,
        Payment.payment_date <= day_end,
    ).scalar() or Decimal("0")

    # Last visit info per customer (single query instead of N+1)
    last_visits = {}
    if customer_ids:
        unique_ids = list(set(customer_ids))
        visit_rows = (
            db.session.query(
                RouteStop.customer_id,
                func.max(RouteStop.route_date).label("last_date"),
            )
            .filter(
                RouteStop.customer_id.in_(unique_ids),
                RouteStop.completed.is_(True),
                RouteStop.route_date < route_date,
            )
            .group_by(RouteStop.customer_id)
            .all()
        )
        last_visits = {row.customer_id: row.last_date for row in visit_rows}

    # Last payment per customer (single query instead of N+1)
    last_payments = {}
    if customer_ids:
        unique_ids = list(set(customer_ids))
        latest_payment_date = (
            db.session.query(
                Payment.customer_id,
                func.max(Payment.id).label("max_id"),
            )
            .filter(Payment.customer_id.in_(unique_ids))
            .group_by(Payment.customer_id)
            .subquery()
        )
        payment_rows = (
            Payment.query
            .join(latest_payment_date, Payment.id == latest_payment_date.c.max_id)
            .all()
        )
        last_payments = {p.customer_id: p for p in payment_rows}

    prev_date = route_date - timedelta(days=1)
    next_date = route_date + timedelta(days=1)
    is_today = route_date == date.today()

    return render_template(
        "route.html",
        stops=stops,
        route_date=route_date,
        collection_target=collection_target,
        collected_today=collected_today,
        sales_today=sales_today,
        last_visits=last_visits,
        last_payments=last_payments,
        prev_date=prev_date,
        next_date=next_date,
        is_today=is_today,
    )


# ---------------------------------------------------------------------------
# Complete stop + optional inline payment
# ---------------------------------------------------------------------------

@bp.route("/stop/<int:id>/complete", methods=["POST"])
@login_required
@staff_required
def complete_stop(id):
    """Mark a route stop as completed. Optionally record a payment."""
    stop = RouteStop.query.get_or_404(id)
    route_date = stop.route_date  # Save before any potential rollback
    stop.completed = True
    stop.completed_at = datetime.now(timezone.utc)

    # Check for inline payment
    amount_str = request.form.get("amount", "").strip()
    amount_sold_str = request.form.get("amount_sold", "").strip()
    payment_type = request.form.get("payment_type", "cash").strip() or "cash"
    if payment_type not in VALID_PAYMENT_TYPES:
        payment_type = "other"
    receipt_number = None

    try:
        amount_paid = Decimal(amount_str) if amount_str else Decimal("0")
    except (InvalidOperation, ValueError):
        amount_paid = Decimal("0")

    try:
        amount_sold = Decimal(amount_sold_str) if amount_sold_str else Decimal("0")
    except (InvalidOperation, ValueError):
        amount_sold = Decimal("0")

    if amount_paid > 0 or amount_sold > 0:
        try:
            # Lock the customer row for safe balance update
            customer = db.session.query(Customer).filter_by(id=stop.customer_id).with_for_update().one()
            previous_balance = customer.balance
            receipt_number = generate_receipt_number()

            new_balance = previous_balance + amount_sold - amount_paid
            if new_balance < 0:
                flash(f"Note: overpayment of ${-new_balance:,.2f} — balance was already zero.", "warning")
                new_balance = Decimal("0")
            customer.balance = new_balance

            payment = Payment(
                customer_id=customer.id,
                amount=amount_paid,
                amount_sold=amount_sold,
                payment_type=payment_type,
                payment_date=datetime.now(timezone.utc),
                receipt_number=receipt_number,
                previous_balance=previous_balance,
                notes=request.form.get("payment_notes", "").strip() or None,
                recorded_by=current_user.id,
            )
            db.session.add(payment)

            # Auto-create invoice when a sale is recorded (consistent with record_payment)
            if amount_sold > 0:
                invoice = Invoice(
                    customer_id=customer.id,
                    invoice_number=receipt_number,
                    amount=amount_sold,
                    invoice_date=date.today(),
                    description=request.form.get("payment_notes", "").strip() or None,
                    payment_type=payment_type,
                    status="paid" if amount_paid >= amount_sold else "unpaid",
                    created_by=current_user.id,
                )
                db.session.add(invoice)

            db.session.flush()  # get payment.id for FIFO tracking
            assert payment.id is not None, "Payment flush failed to generate ID"

            # Mark old unpaid invoices paid FIFO if excess payment
            if amount_paid > 0:
                excess = amount_paid - amount_sold
                if excess > 0:
                    unpaid_invoices = Invoice.query.filter_by(
                        customer_id=customer.id, status="unpaid"
                    ).order_by(Invoice.invoice_date.asc()).all()
                    for inv in unpaid_invoices:
                        if inv.invoice_number == receipt_number:
                            continue
                        if excess >= inv.amount:
                            inv.status = "paid"
                            inv.payment_type = payment_type
                            inv.paid_by_payment_id = payment.id
                            excess -= inv.amount
                        else:
                            break

            parts = []
            if amount_sold > 0:
                parts.append(f"Sold ${amount_sold:,.2f}")
            if amount_paid > 0:
                parts.append(f"Paid ${amount_paid:,.2f}")
            desc = ". ".join(parts) + f". Receipt: {receipt_number}"

            db.session.add(ActivityLog(
                customer_id=customer.id,
                user_id=current_user.id,
                action="payment_recorded",
                description=desc,
            ))
            audit("payment_recorded", f"Route payment: {desc} for '{customer.name}'")
        except Exception:
            logging.exception("Inline payment failed for stop #%s", id)
            db.session.rollback()
            flash("Payment failed — stop was not completed. Please try again.", "error")
            return redirect(url_for("route.index", date=route_date.isoformat()))

    audit("stop_completed", f"Completed route stop for customer #{stop.customer_id} on {stop.route_date}")

    try:
        db.session.commit()
    except Exception:
        logging.exception("Failed to commit stop completion for stop #%s", id)
        db.session.rollback()
        flash("Failed to save. Please try again.", "error")
        return redirect(url_for("route.index"))

    # For HTMX, return the updated stop card with trigger to refresh totals
    if request.headers.get("HX-Request"):
        response = make_response(render_template("partials/stop_card.html", stop=stop, receipt_number=receipt_number))
        response.headers["HX-Trigger"] = "stopCompleted"
        return response

    flash("Stop completed.", "success")
    return redirect(url_for("route.index", date=stop.route_date.isoformat()))


@bp.route("/stop/<int:id>/uncomplete", methods=["POST"])
@login_required
@staff_required
def uncomplete_stop(id):
    """Unmark a route stop."""
    stop = RouteStop.query.get_or_404(id)
    stop.completed = False
    stop.completed_at = None
    audit("stop_uncompleted", f"Uncompleted route stop for customer #{stop.customer_id} on {stop.route_date}")
    db.session.commit()

    if request.headers.get("HX-Request"):
        response = make_response(render_template("partials/stop_card.html", stop=stop))
        response.headers["HX-Trigger"] = "stopCompleted"
        return response

    flash("Stop unmarked. Note: any payment recorded during completion has NOT been reversed.", "warning")
    return redirect(url_for("route.index", date=stop.route_date.isoformat()))


# ---------------------------------------------------------------------------
# Stop notes
# ---------------------------------------------------------------------------

@bp.route("/stop/<int:id>/notes", methods=["POST"])
@login_required
@staff_required
def update_stop_notes(id):
    """Update notes on a route stop."""
    stop = RouteStop.query.get_or_404(id)
    stop.notes = request.form.get("notes", "").strip()
    db.session.commit()

    flash("Stop notes updated.", "success")
    return redirect(url_for("route.index", date=stop.route_date.isoformat()))


# ---------------------------------------------------------------------------
# Route summary
# ---------------------------------------------------------------------------

@bp.route("/summary")
@login_required
def summary():
    """Summary stats for today's (or requested date's) route."""
    date_param = request.args.get("date", "")
    if date_param:
        try:
            route_date = date.fromisoformat(date_param)
        except ValueError:
            route_date = date.today()
    else:
        route_date = date.today()

    total_stops = RouteStop.query.filter(RouteStop.route_date == route_date).count()
    completed_stops = RouteStop.query.filter(
        RouteStop.route_date == route_date,
        RouteStop.completed.is_(True),
    ).count()

    day_start = datetime(route_date.year, route_date.month, route_date.day, tzinfo=timezone.utc)
    day_end = datetime(route_date.year, route_date.month, route_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    payment_stats = db.session.query(
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
    ).filter(
        Payment.payment_date >= day_start,
        Payment.payment_date <= day_end,
    ).first()
    payment_count = payment_stats[0]
    payment_sum = payment_stats[1] or Decimal("0")

    stops = (
        RouteStop.query
        .options(joinedload(RouteStop.customer))
        .join(Customer)
        .filter(RouteStop.route_date == route_date)
        .order_by(RouteStop.sequence)
        .all()
    )

    next_date = route_date + timedelta(days=1)
    next_day_stops_list = (
        RouteStop.query
        .options(joinedload(RouteStop.customer))
        .join(Customer)
        .filter(RouteStop.route_date == next_date)
        .order_by(RouteStop.sequence)
        .all()
    )
    next_day_stops = len(next_day_stops_list)

    return render_template(
        "route_summary.html",
        route_date=route_date,
        total_stops=total_stops,
        completed_stops=completed_stops,
        stops=stops,
        payment_count=payment_count,
        payment_sum=payment_sum,
        next_date=next_date,
        next_day_stops=next_day_stops,
        next_day_stops_list=next_day_stops_list,
    )


# ---------------------------------------------------------------------------
# Receipts ZIP
# ---------------------------------------------------------------------------

@bp.route("/receipts/<date_str>")
@login_required
def receipts_zip(date_str):
    """Generate a ZIP of all payment receipt PDFs for the given date."""
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for("route.index"))

    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    payments = (
        Payment.query
        .options(joinedload(Payment.customer))
        .filter(Payment.payment_date >= day_start, Payment.payment_date <= day_end)
        .all()
    )

    if not payments:
        flash("No payments found for that date.", "warning")
        return redirect(url_for("route.summary", date=date_str))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for payment in payments:
            customer = payment.customer
            pdf_bytes = generate_receipt_pdf(payment, customer)
            filename = f"{payment.receipt_number}.pdf"
            zf.writestr(filename, pdf_bytes)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"receipts-{date_str}.zip",
    )
