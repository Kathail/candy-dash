"""Reporting routes with CSV and Excel export support."""

import csv
import io
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request, Response, flash
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.helpers import format_currency, format_date
from app.models import Customer, Payment, User

bp = Blueprint("reports", __name__, url_prefix="/reports")

# Maximum report range to prevent full-table scans
MAX_REPORT_DAYS = 366


@bp.before_request
@login_required
def before_request():
    """Require login for all report routes."""
    pass


def _parse_date_range():
    """Parse start_date and end_date from query params. Returns (start, end) datetimes.

    Enforces start <= end and caps range at MAX_REPORT_DAYS.
    """
    start_str = request.args.get("start_date", "")
    end_str = request.args.get("end_date", "")

    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        today = date.today()
        start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)

    try:
        end = datetime.strptime(end_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        end = datetime.now(timezone.utc)

    # Don't allow future end dates
    now = datetime.now(timezone.utc)
    if end > now:
        end = now

    # Swap if reversed
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), \
                     start.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Cap range
    max_start = end - timedelta(days=MAX_REPORT_DAYS)
    if start < max_start:
        start = max_start.replace(hour=0, minute=0, second=0, microsecond=0)

    return start, end


def _csv_response(rows, headers, filename):
    """Build a CSV download response."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


def _xlsx_response(rows, headers, filename):
    """Build an Excel download response using openpyxl."""
    try:
        from openpyxl import Workbook
    except ImportError:
        return Response("openpyxl is not installed.", status=500)

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(list(row))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@bp.route("/")
def index():
    """Reports landing page with date range picker."""
    return render_template("reports.html")


@bp.route("/financial")
def financial():
    """Financial report: payment summary, by city, by customer for date range."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    # Overall summary
    summary = db.session.query(
        func.count(Payment.id).label("count"),
        func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
    ).filter(
        Payment.payment_date >= start,
        Payment.payment_date <= end,
    ).first()

    # By city
    by_city = (
        db.session.query(
            Customer.city,
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= start, Payment.payment_date <= end)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .all()
    )

    # By customer
    by_customer = (
        db.session.query(
            Customer.name,
            Customer.city,
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= start, Payment.payment_date <= end)
        .group_by(Customer.id, Customer.name, Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .limit(500)
        .all()
    )

    # Export
    if fmt in ("csv", "xlsx"):
        headers = ["Customer", "City", "Payment Count", "Total"]
        rows = [
            (row.name, row.city or "", row.count, float(row.total))
            for row in by_customer
        ]
        filename = f"financial_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return _csv_response(rows, headers, f"{filename}.csv")
        return _xlsx_response(rows, headers, f"{filename}.xlsx")

    return render_template(
        "reports/financial.html",
        summary=summary,
        by_city=by_city,
        by_customer=by_customer,
        start=start,
        end=end,
    )


@bp.route("/tax")
def tax():
    """Tax report: payments grouped by tax-exempt vs taxable customers."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    rows = (
        db.session.query(
            Customer.name,
            Customer.city,
            Customer.tax_exempt,
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= start, Payment.payment_date <= end)
        .group_by(Customer.id, Customer.name, Customer.city, Customer.tax_exempt)
        .order_by(Customer.tax_exempt.desc(), func.sum(Payment.amount).desc())
        .limit(500)
        .all()
    )

    # Summaries
    taxable_total = sum(r.total for r in rows if not r.tax_exempt)
    exempt_total = sum(r.total for r in rows if r.tax_exempt)

    if fmt in ("csv", "xlsx"):
        headers = ["Customer", "City", "Tax Exempt", "Payment Count", "Total"]
        export_rows = [
            (r.name, r.city or "", "Yes" if r.tax_exempt else "No", r.count, float(r.total))
            for r in rows
        ]
        filename = f"tax_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return _csv_response(export_rows, headers, f"{filename}.csv")
        return _xlsx_response(export_rows, headers, f"{filename}.xlsx")

    return render_template(
        "reports/tax.html",
        rows=rows,
        taxable_total=taxable_total,
        exempt_total=exempt_total,
        start=start,
        end=end,
    )


@bp.route("/collections")
def collections():
    """Collections report by sales rep (recorded_by) for date range."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    rows = (
        db.session.query(
            User.username,
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.recorded_by == User.id)
        .filter(Payment.payment_date >= start, Payment.payment_date <= end)
        .group_by(User.id, User.username)
        .order_by(func.sum(Payment.amount).desc())
        .all()
    )

    if fmt in ("csv", "xlsx"):
        headers = ["Sales Rep", "Payment Count", "Total"]
        export_rows = [(r.username, r.count, float(r.total)) for r in rows]
        filename = f"collections_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return _csv_response(export_rows, headers, f"{filename}.csv")
        return _xlsx_response(export_rows, headers, f"{filename}.xlsx")

    return render_template(
        "reports/collections.html",
        rows=rows,
        start=start,
        end=end,
    )
