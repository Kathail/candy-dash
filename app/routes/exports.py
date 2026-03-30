"""CSV export routes for customers, payments, and route history (admin only)."""

import csv
import io
from datetime import datetime, timezone, date

from flask import Blueprint, Response, request
from flask_login import login_required

from app import db
from app.helpers import admin_required, sanitize_csv_value
from app.models import Customer, Payment, RouteStop

bp = Blueprint("exports", __name__, url_prefix="/exports")


@bp.before_request
@login_required
def before_request():
    """Require login for all export routes."""
    pass


def _csv_response(rows, headers, filename):
    """Build a CSV download response."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([[sanitize_csv_value(cell) for cell in row] for row in rows])
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


def _parse_date_range():
    """Parse optional start_date and end_date from query params."""
    start_str = request.args.get("start_date", "")
    end_str = request.args.get("end_date", "")

    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        start = None

    try:
        end = datetime.strptime(end_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        end = None

    return start, end


@bp.route("/customers")
@admin_required
def customers():
    """CSV export of all customers."""
    all_customers = Customer.query.order_by(Customer.name).all()

    headers = [
        "ID", "Name", "Address", "City", "Phone", "Status",
        "Balance", "Tax Exempt", "Lead Source", "Notes", "Created At",
    ]
    rows = [
        (
            c.id,
            c.name,
            c.address or "",
            c.city or "",
            c.phone or "",
            c.status,
            str(c.balance) if c.balance else "0",
            "Yes" if c.tax_exempt else "No",
            c.lead_source or "",
            c.notes or "",
            c.created_at.isoformat() if c.created_at else "",
        )
        for c in all_customers
    ]

    return _csv_response(rows, headers, "customers_export.csv")


@bp.route("/payments")
@admin_required
def payments():
    """CSV export of payments, optionally filtered by date range."""
    start, end = _parse_date_range()

    query = (
        Payment.query
        .join(Customer, Payment.customer_id == Customer.id)
        .order_by(Payment.payment_date.desc())
    )

    if start:
        query = query.filter(Payment.payment_date >= start)
    if end:
        query = query.filter(Payment.payment_date <= end)

    all_payments = query.all()

    headers = [
        "ID", "Receipt Number", "Customer", "Amount",
        "Previous Balance", "Payment Date", "Notes", "Recorded By",
    ]
    rows = []
    for p in all_payments:
        customer = p.customer
        recorder = p.recorder
        rows.append((
            p.id,
            p.receipt_number,
            customer.name if customer else "",
            str(p.amount),
            str(p.previous_balance),
            p.payment_date.isoformat() if p.payment_date else "",
            p.notes or "",
            recorder.username if recorder else "",
        ))

    filename = "payments_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"
    filename += ".csv"

    return _csv_response(rows, headers, filename)


@bp.route("/route-history")
@admin_required
def route_history():
    """CSV export of route stops, optionally filtered by date range."""
    start, end = _parse_date_range()

    query = (
        RouteStop.query
        .join(Customer, RouteStop.customer_id == Customer.id)
        .order_by(RouteStop.route_date.desc(), RouteStop.sequence)
    )

    if start:
        query = query.filter(RouteStop.route_date >= start.date())
    if end:
        query = query.filter(RouteStop.route_date <= end.date())

    all_stops = query.all()

    headers = [
        "ID", "Route Date", "Sequence", "Customer", "City",
        "Completed", "Completed At", "Notes", "Created By",
    ]
    rows = []
    for s in all_stops:
        customer = s.customer
        creator = s.creator
        rows.append((
            s.id,
            s.route_date.isoformat() if s.route_date else "",
            s.sequence,
            customer.name if customer else "",
            customer.city if customer else "",
            "Yes" if s.completed else "No",
            s.completed_at.isoformat() if s.completed_at else "",
            s.notes or "",
            creator.username if creator else "",
        ))

    filename = "route_history_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"
    filename += ".csv"

    return _csv_response(rows, headers, filename)
