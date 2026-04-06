"""Reporting routes with CSV and Excel export support."""

from datetime import datetime, timezone, date
from decimal import Decimal

from flask import Blueprint, render_template, request, flash
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.helpers import staff_required, export_response, parse_date_range
from app.models import Customer, Invoice, User

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
    """Parse date range using shared helper, capped at MAX_REPORT_DAYS."""
    return parse_date_range(max_days=MAX_REPORT_DAYS)





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

    query = (
        db.session.query(
            Invoice.invoice_date,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount), Decimal("0")).label("total"),
        )
        .filter(Invoice.invoice_date >= start_date, Invoice.invoice_date <= end_date)
        .group_by(Invoice.invoice_date)
        .order_by(Invoice.invoice_date.desc())
    )

    if fmt in ("csv", "xlsx", "pdf"):
        rows = query.all()
        headers = ["Date", "Sales Count", "Total"]
        export_rows = [(str(r.invoice_date), r.count, str(r.total)) for r in rows]
        filename = f"daily_sales_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        return export_response(export_rows, headers, filename, fmt, title="Daily Sales")

    rows = query.all()
    grand_total = sum(r.total for r in rows)
    grand_count = sum(r.count for r in rows)

    # Chart data (all rows, chronological order, as floats for JSON)
    chart_labels = [r.invoice_date.strftime('%b %d') for r in reversed(rows)]
    chart_data = [float(r.total) for r in reversed(rows)]

    # Paginate for display
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_rows = rows[(page - 1) * per_page : page * per_page]

    return render_template(
        "reports/daily_sales.html",
        rows=page_rows,
        chart_labels=chart_labels,
        chart_data=chart_data,
        grand_total=grand_total,
        grand_count=grand_count,
        start=start,
        end=end,
        page=page,
        total_pages=total_pages,
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
    by_customer_query = (
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
    )

    # Export gets all data
    if fmt in ("csv", "xlsx", "pdf"):
        by_customer = by_customer_query.limit(500).all()
        headers = ["Customer", "City", "Sales Count", "Total"]
        rows = [
            (row.name, row.city or "", row.count, str(row.total))
            for row in by_customer
        ]
        filename = f"sales_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        return export_response(rows, headers, filename, fmt, title="Sales Report")

    # Paginate for display (SQL-level)
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total_count = by_customer_query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = min(page, total_pages)
    by_customer = by_customer_query.offset((page - 1) * per_page).limit(per_page).all()

    return render_template(
        "reports/financial.html",
        summary=summary,
        by_city=by_city,
        by_customer=by_customer,
        start=start,
        end=end,
        page=page,
        total_pages=total_pages,
    )


@bp.route("/tax")
def tax():
    """Tax report: sales grouped by tax-exempt vs taxable customers."""
    start, end = _parse_date_range()
    fmt = request.args.get("format", "").lower()

    start_date = start.date() if hasattr(start, 'date') else start
    end_date = end.date() if hasattr(end, 'date') else end

    base_query = (
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
    )

    if fmt in ("csv", "xlsx", "pdf"):
        all_rows = (
            base_query
            .order_by(Customer.tax_exempt.desc(), func.sum(Invoice.amount).desc())
            .limit(500)
            .all()
        )
        headers = ["Customer", "City", "Tax Exempt", "Sales Count", "Total"]
        export_rows = [
            (r.name, r.city or "", "Yes" if r.tax_exempt else "No", r.count, str(r.total))
            for r in all_rows
        ]
        filename = f"tax_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        return export_response(export_rows, headers, filename, fmt, title="Tax Report")

    taxable_rows = (
        base_query
        .filter(Customer.tax_exempt.isnot(True))
        .order_by(func.sum(Invoice.amount).desc())
        .all()
    )
    exempt_rows = (
        base_query
        .filter(Customer.tax_exempt.is_(True))
        .order_by(func.sum(Invoice.amount).desc())
        .all()
    )

    taxable_total = sum(r.total for r in taxable_rows)
    exempt_total = sum(r.total for r in exempt_rows)

    return render_template(
        "reports/tax.html",
        taxable_rows=taxable_rows,
        exempt_rows=exempt_rows,
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

    if fmt in ("csv", "xlsx", "pdf"):
        headers = ["Sales Rep", "Sales Count", "Total"]
        export_rows = [(r.username, r.count, str(r.total)) for r in rows]
        filename = f"sales_by_rep_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        return export_response(export_rows, headers, filename, fmt, title="Sales by Rep")

    return render_template(
        "reports/collections.html",
        rows=rows,
        start=start,
        end=end,
    )
