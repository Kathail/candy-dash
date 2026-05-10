"""Export routes for customers, payments, and route history (admin only)."""

from flask import Blueprint, request
from flask_login import login_required

from app import db
from app.helpers import admin_required, export_response, parse_date_range_optional, format_date
from app.models import Customer, Invoice, Payment, RouteStop, User


def _money(val):
    """Format a Decimal as '1234.56' (always 2 decimals, no $ sign for exports)."""
    if val is None:
        return "0.00"
    return f"{val:.2f}"


def _dt(val, fmt="%Y-%m-%d %I:%M %p"):
    """Format a datetime for export. Returns empty string for None."""
    if val is None:
        return ""
    return format_date(val, fmt)

bp = Blueprint("exports", __name__, url_prefix="/exports")


@bp.before_request
@login_required
@admin_required
def before_request():
    """Require login and admin role for all export routes."""
    pass


@bp.route("/customers")
@admin_required
def customers():
    """Export all customers."""
    fmt = request.args.get("format", "csv").lower()
    q = (
        db.session.query(
            Customer.id, Customer.name, Customer.address, Customer.city, Customer.phone,
            Customer.status, Customer.balance, Customer.tax_exempt, Customer.lead_source,
            Customer.notes, Customer.created_at,
        )
        .order_by(Customer.name)
        .yield_per(500)
    )

    headers = [
        "ID", "Name", "Address", "City", "Phone", "Status",
        "Balance", "Tax Exempt", "Lead Source", "Notes", "Created At",
    ]

    def rows():
        for r in q:
            yield (
                r.id, r.name, r.address or "", r.city or "", r.phone or "",
                r.status, _money(r.balance), "Yes" if r.tax_exempt else "No",
                r.lead_source or "", r.notes or "", _dt(r.created_at),
            )

    return export_response(rows(), headers, "customers_export", fmt, title="Customers")


@bp.route("/payments")
@admin_required
def payments():
    """Export payments, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        db.session.query(
            Payment.id, Payment.receipt_number, Customer.name, Payment.amount_sold,
            Payment.amount, Payment.payment_type, Payment.previous_balance,
            Payment.payment_date, Payment.notes, User.username,
        )
        .join(Customer, Payment.customer_id == Customer.id)
        .outerjoin(User, Payment.recorded_by == User.id)
        .order_by(Payment.payment_date.desc())
    )

    if start:
        query = query.filter(Payment.payment_date >= start)
    if end:
        query = query.filter(Payment.payment_date <= end)

    q = query.yield_per(500)

    headers = [
        "ID", "Receipt Number", "Customer", "Amount Sold", "Amount Paid",
        "Payment Type", "Previous Balance", "Payment Date", "Notes", "Recorded By",
    ]

    def rows():
        for r in q:
            yield (
                r.id, r.receipt_number, r.name or "",
                _money(r.amount_sold), _money(r.amount),
                r.payment_type or "", _money(r.previous_balance),
                _dt(r.payment_date), r.notes or "", r.username or "",
            )

    filename = "payments_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"

    return export_response(rows(), headers, filename, fmt, title="Payments")


@bp.route("/route-history")
@admin_required
def route_history():
    """Export route stops, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        db.session.query(
            RouteStop.id, RouteStop.route_date, RouteStop.sequence,
            Customer.name, Customer.city, RouteStop.completed,
            RouteStop.completed_at, RouteStop.notes, User.username,
        )
        .join(Customer, RouteStop.customer_id == Customer.id)
        .outerjoin(User, RouteStop.created_by == User.id)
        .order_by(RouteStop.route_date.desc(), RouteStop.sequence)
    )

    if start:
        query = query.filter(RouteStop.route_date >= start.date())
    if end:
        query = query.filter(RouteStop.route_date <= end.date())

    q = query.yield_per(500)

    headers = [
        "ID", "Route Date", "Sequence", "Customer", "City",
        "Completed", "Completed At", "Notes", "Created By",
    ]

    def rows():
        for r in q:
            yield (
                r.id,
                r.route_date.strftime("%Y-%m-%d") if r.route_date else "",
                r.sequence, r.name or "", r.city or "",
                "Yes" if r.completed else "No",
                _dt(r.completed_at), r.notes or "", r.username or "",
            )

    filename = "route_history_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"

    return export_response(rows(), headers, filename, fmt, title="Route History")


@bp.route("/invoices")
@admin_required
def invoices():
    """Export invoices, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        db.session.query(
            Invoice.id, Invoice.invoice_number, Customer.name, Invoice.amount,
            Invoice.status, Invoice.invoice_date, Invoice.payment_type,
            Invoice.description, User.username,
        )
        .join(Customer, Invoice.customer_id == Customer.id)
        .outerjoin(User, Invoice.created_by == User.id)
        .order_by(Invoice.invoice_date.desc())
    )

    if start:
        query = query.filter(Invoice.invoice_date >= start.date())
    if end:
        query = query.filter(Invoice.invoice_date <= end.date())

    q = query.yield_per(500)

    headers = [
        "ID", "Invoice Number", "Customer", "Amount", "Status",
        "Invoice Date", "Payment Type", "Description", "Created By",
    ]

    def rows():
        for r in q:
            yield (
                r.id, r.invoice_number or "", r.name or "",
                _money(r.amount), r.status,
                r.invoice_date.strftime("%Y-%m-%d") if r.invoice_date else "",
                r.payment_type or "", r.description or "", r.username or "",
            )

    filename = "invoices_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"

    return export_response(rows(), headers, filename, fmt, title="Invoices")
