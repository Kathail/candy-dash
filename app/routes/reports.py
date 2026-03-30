"""Reporting routes with CSV and Excel export support."""

import io
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request, Response, flash
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.helpers import format_currency, format_date, staff_required, csv_response
from app.models import Customer, Payment, Invoice, User

bp = Blueprint("reports", __name__, url_prefix="/reports")

# Maximum report range to prevent full-table scans
MAX_REPORT_DAYS = 366


@bp.before_request
@login_required
@staff_required
def before_request():
    """Require login and non-demo role for all report routes."""
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


@bp.route("/daily-sales")
def daily_sales():
    """Daily sales breakdown for the selected period."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    start_date = start.date() if hasattr(start, 'date') else start
    end_date = end.date() if hasattr(end, 'date') else end

    rows = (
        db.session.query(
            Invoice.invoice_date,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(Invoice.invoice_date)
        .order_by(Invoice.invoice_date.desc())
        .all()
    )

    grand_total = sum(r.total for r in rows)
    grand_count = sum(r.count for r in rows)

    if fmt in ("csv", "xlsx"):
        headers = ["Date", "Sales Count", "Total"]
        export_rows = [(str(r.invoice_date), r.count, str(r.total)) for r in rows]
        filename = f"daily_sales_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return csv_response(export_rows, headers, f"{filename}.csv")
        return _xlsx_response(export_rows, headers, f"{filename}.xlsx")

    return render_template(
        "reports/daily_sales.html",
        rows=rows,
        grand_total=grand_total,
        grand_count=grand_count,
        start=start,
        end=end,
    )


@bp.route("/financial")
def financial():
    """Sales report: total sales by city and customer for date range."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    start_date = start.date() if hasattr(start, 'date') else start
    end_date = end.date() if hasattr(end, 'date') else end

    # Overall summary (sales from invoices)
    summary = db.session.query(
        func.count(Invoice.id).label("count"),
        func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
    ).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date,
    ).first()

    # By city
    by_city = (
        db.session.query(
            Customer.city,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(Customer.city)
        .order_by(func.sum(Invoice.amount).desc())
        .all()
    )

    # By customer
    by_customer = (
        db.session.query(
            Customer.name,
            Customer.city,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(Customer.id, Customer.name, Customer.city)
        .order_by(func.sum(Invoice.amount).desc())
        .limit(500)
        .all()
    )

    # Export
    if fmt in ("csv", "xlsx"):
        headers = ["Customer", "City", "Sales Count", "Total"]
        rows = [
            (row.name, row.city or "", row.count, str(row.total))
            for row in by_customer
        ]
        filename = f"sales_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return csv_response(rows, headers, f"{filename}.csv")
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
    """Tax report: sales grouped by tax-exempt vs taxable customers."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    start_date = start.date() if hasattr(start, 'date') else start
    end_date = end.date() if hasattr(end, 'date') else end

    rows = (
        db.session.query(
            Customer.name,
            Customer.city,
            Customer.tax_exempt,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(Customer.id, Customer.name, Customer.city, Customer.tax_exempt)
        .order_by(Customer.tax_exempt.desc(), func.sum(Invoice.amount).desc())
        .limit(500)
        .all()
    )

    # Summaries
    taxable_total = sum(r.total for r in rows if not r.tax_exempt)
    exempt_total = sum(r.total for r in rows if r.tax_exempt)

    if fmt in ("csv", "xlsx"):
        headers = ["Customer", "City", "Tax Exempt", "Sales Count", "Total"]
        export_rows = [
            (r.name, r.city or "", "Yes" if r.tax_exempt else "No", r.count, str(r.total))
            for r in rows
        ]
        filename = f"tax_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return csv_response(export_rows, headers, f"{filename}.csv")
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
    """Sales report by rep for date range."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    start_date = start.date() if hasattr(start, 'date') else start
    end_date = end.date() if hasattr(end, 'date') else end

    rows = (
        db.session.query(
            User.username,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .join(Invoice, Invoice.created_by == User.id)
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(User.id, User.username)
        .order_by(func.sum(Invoice.amount).desc())
        .all()
    )

    if fmt in ("csv", "xlsx"):
        headers = ["Sales Rep", "Sales Count", "Total"]
        export_rows = [(r.username, r.count, str(r.total)) for r in rows]
        filename = f"sales_by_rep_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        if fmt == "csv":
            return csv_response(export_rows, headers, f"{filename}.csv")
        return _xlsx_response(export_rows, headers, f"{filename}.xlsx")

    return render_template(
        "reports/collections.html",
        rows=rows,
        start=start,
        end=end,
    )
