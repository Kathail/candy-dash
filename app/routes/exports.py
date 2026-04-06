"""Export routes for customers, payments, and route history (admin only)."""

from flask import Blueprint, request
from flask_login import login_required

from sqlalchemy.orm import joinedload

from app import db
from app.helpers import admin_required, export_response, parse_date_range_optional
from app.models import Customer, Invoice, Payment, RouteStop

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

    return export_response(rows, headers, "customers_export", fmt, title="Customers")


@bp.route("/payments")
@admin_required
def payments():
    """Export payments, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        Payment.query
        .options(joinedload(Payment.customer), joinedload(Payment.recorder))
        .join(Customer, Payment.customer_id == Customer.id)
        .order_by(Payment.payment_date.desc())
    )

    if start:
        query = query.filter(Payment.payment_date >= start)
    if end:
        query = query.filter(Payment.payment_date <= end)

    all_payments = query.all()

    headers = [
        "ID", "Receipt Number", "Customer", "Amount Sold", "Amount Paid",
        "Payment Type", "Previous Balance", "Payment Date", "Notes", "Recorded By",
    ]
    rows = []
    for p in all_payments:
        customer = p.customer
        recorder = p.recorder
        rows.append((
            p.id,
            p.receipt_number,
            customer.name if customer else "",
            str(p.amount_sold or 0),
            str(p.amount),
            p.payment_type or "",
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

    return export_response(rows, headers, filename, fmt, title="Payments")


@bp.route("/route-history")
@admin_required
def route_history():
    """Export route stops, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        RouteStop.query
        .options(joinedload(RouteStop.customer), joinedload(RouteStop.creator))
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

    return export_response(rows, headers, filename, fmt, title="Route History")


@bp.route("/invoices")
@admin_required
def invoices():
    """Export invoices, optionally filtered by date range."""
    fmt = request.args.get("format", "csv").lower()
    start, end = parse_date_range_optional()

    query = (
        Invoice.query
        .options(joinedload(Invoice.customer), joinedload(Invoice.creator))
        .join(Customer, Invoice.customer_id == Customer.id)
        .order_by(Invoice.invoice_date.desc())
    )

    if start:
        query = query.filter(Invoice.invoice_date >= start.date())
    if end:
        query = query.filter(Invoice.invoice_date <= end.date())

    all_invoices = query.all()

    headers = [
        "ID", "Invoice Number", "Customer", "Amount", "Status",
        "Invoice Date", "Payment Type", "Description", "Created By",
    ]
    rows = []
    for inv in all_invoices:
        rows.append((
            inv.id,
            inv.invoice_number or "",
            inv.customer.name if inv.customer else "",
            str(inv.amount),
            inv.status,
            inv.invoice_date.isoformat() if inv.invoice_date else "",
            inv.payment_type or "",
            inv.description or "",
            inv.creator.username if inv.creator else "",
        ))

    filename = "invoices_export"
    if start:
        filename += f"_from_{start.strftime('%Y%m%d')}"
    if end:
        filename += f"_to_{end.strftime('%Y%m%d')}"

    return export_response(rows, headers, filename, fmt, title="Invoices")
