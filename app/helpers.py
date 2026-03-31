"""Shared helpers: decorators, PDF generation, template filters."""

import io
from decimal import Decimal
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

# Toronto timezone (handles EST/EDT automatically)
TZ_DISPLAY = ZoneInfo("America/Toronto")
from functools import wraps
from urllib.parse import urlparse, urljoin

from flask import abort, redirect, request, url_for
from flask_login import current_user
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def sanitize_csv_value(val):
    """Prevent CSV formula injection by prefixing dangerous characters."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + val
    return val


def admin_required(f):
    """Decorator that requires the current user to be an admin or owner."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        if current_user.role not in ("admin", "owner"):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def staff_required(f):
    """Decorator that requires admin or owner role (blocks demo users)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.is_demo:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def audit(action, details="", user_id=None):
    """Record an entry in the audit log. Can be called from any blueprint."""
    from app import db
    from app.models import AdminAuditLog

    if user_id is None:
        user_id = current_user.id if current_user.is_authenticated else None

    if user_id is not None:
        db.session.add(AdminAuditLog(
            user_id=user_id,
            action=action,
            details=details,
        ))


def safe_redirect(target):
    """Validate redirect URL to prevent open redirect attacks."""
    default = url_for("dashboard.index")
    if not target:
        return default
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    if test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc:
        return target
    return default


def format_currency(value):
    """Template filter: format a number as currency."""
    if value is None:
        return "$0.00"
    return f"${Decimal(str(value)):,.2f}"


def format_date(value, fmt="%b %d, %Y"):
    """Template filter: format a datetime or date in America/Toronto timezone."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(fmt)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(TZ_DISPLAY)
    return value.strftime(fmt)


def csv_response(rows, headers, filename):
    """Build a CSV download response with formula-injection protection."""
    import csv
    from flask import Response
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([sanitize_csv_value(cell) for cell in row])
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


def parse_date_range(max_days=366):
    """Parse start_date and end_date from query params with validation.

    Enforces start <= end, caps range at max_days, and prevents future end dates.
    Returns (start, end) as timezone-aware datetimes.
    """
    from datetime import timedelta

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

    now = datetime.now(timezone.utc)
    if end > now:
        end = now

    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), \
                     start.replace(hour=23, minute=59, second=59, microsecond=999999)

    max_start = end - timedelta(days=max_days)
    if start < max_start:
        start = max_start.replace(hour=0, minute=0, second=0, microsecond=0)

    return start, end


def parse_date_range_optional():
    """Parse optional start_date and end_date from query params.

    Returns (start, end) where either may be None if not provided.
    """
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


def xlsx_response(rows, headers, filename):
    """Build an Excel download response using openpyxl."""
    try:
        from openpyxl import Workbook
    except ImportError:
        from flask import Response
        return Response("openpyxl is not installed.", status=500)

    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([sanitize_csv_value(cell) for cell in row])
    wb.save(buf)
    buf.seek(0)
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


def pdf_table_response(rows, headers, filename, title=None):
    """Build a PDF table download using reportlab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    if title:
        title_style = ParagraphStyle("TableTitle", parent=styles["Heading1"], fontSize=16, alignment=1)
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 0.3 * inch))

    # Build table data with header row
    table_data = [headers]
    for row in rows:
        table_data.append([str(sanitize_csv_value(cell)) for cell in row])

    # Auto column widths (evenly distributed)
    ncols = len(headers)
    col_width = 7.0 * inch / max(ncols, 1)
    table = Table(table_data, colWidths=[col_width] * ncols)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#4b5563")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


def export_response(rows, headers, filename_base, fmt="csv", title=None):
    """Return rows in the requested format (csv, xlsx, or pdf)."""
    if fmt == "xlsx":
        return xlsx_response(rows, headers, f"{filename_base}.xlsx")
    elif fmt == "pdf":
        return pdf_table_response(rows, headers, f"{filename_base}.pdf", title=title)
    return csv_response(rows, headers, f"{filename_base}.csv")


def generate_receipt_number(payment_date=None, max_retries=5):
    """Generate a unique invoice number in format INV-YYYYMMDD-XXXX.

    Uses SELECT ... FOR UPDATE SKIP LOCKED (Postgres) to prevent race
    conditions without deadlocking concurrent transactions.
    Falls back to UUID suffix if sequence collides after retries.
    """
    import logging
    import uuid
    from app.models import Payment
    from app import db

    if payment_date is None:
        payment_date = datetime.now(timezone.utc)

    date_str = payment_date.strftime("%Y%m%d")
    prefix = f"INV-{date_str}-"

    for attempt in range(max_retries):
        try:
            last = (
                Payment.query
                .filter(Payment.receipt_number.like(f"{prefix}%"))
                .order_by(Payment.receipt_number.desc())
                .with_for_update(skip_locked=True)
                .first()
            )

            if last and last.receipt_number.startswith(prefix):
                try:
                    seq = int(last.receipt_number[len(prefix):]) + 1
                except ValueError:
                    seq = 1
            else:
                seq = 1

            # Also check unflushed session objects for higher sequences
            for obj in db.session.new:
                if isinstance(obj, Payment) and hasattr(obj, 'receipt_number') and obj.receipt_number:
                    if obj.receipt_number.startswith(prefix):
                        try:
                            pending_seq = int(obj.receipt_number[len(prefix):]) + 1
                            seq = max(seq, pending_seq)
                        except ValueError:
                            pass

            return f"{prefix}{seq:04d}"
        except Exception:
            logging.exception("Receipt number generation failed (attempt %d/%d)", attempt + 1, max_retries)
            db.session.rollback()
            if attempt == max_retries - 1:
                short_uuid = uuid.uuid4().hex[:6].upper()
                return f"{prefix}{short_uuid}"


def generate_receipt_pdf(payment, customer):
    """Generate a PDF receipt for a payment. Returns bytes."""
    import os
    from reportlab.platypus import Image

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReceiptTitle", parent=styles["Heading1"], fontSize=18, alignment=1
    )
    normal_center = ParagraphStyle(
        "NormalCenter", parent=styles["Normal"], alignment=1
    )

    elements = []

    # Logo
    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "img", "logo.png")
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=1.2 * inch, height=1.2 * inch)
            logo.hAlign = "CENTER"
            elements.append(logo)
            elements.append(Spacer(1, 12))
        except Exception:
            pass

    elements.append(Paragraph("Northern Sweet Supply", title_style))
    elements.append(Paragraph("Payment Receipt", normal_center))
    elements.append(Spacer(1, 0.3 * inch))

    amount_sold = getattr(payment, "amount_sold", None) or Decimal("0")
    new_balance = payment.previous_balance + amount_sold - payment.amount

    data = [
        ["Invoice #:", payment.receipt_number],
        ["Date:", format_date(payment.payment_date, "%B %d, %Y")],
        ["Customer:", customer.name],
        ["Payment Type:", (payment.payment_type or "cash").capitalize()],
        ["", ""],
        ["Previous Balance:", format_currency(payment.previous_balance)],
    ]
    if amount_sold > 0:
        data.append(["Sale Amount:", format_currency(amount_sold)])
    if payment.amount > 0:
        data.append(["Payment Amount:", format_currency(payment.amount)])
    data.append(["New Balance:", format_currency(new_balance)])

    if payment.notes:
        data.append(["Notes:", payment.notes])

    separator_row = 4  # the empty row
    table = Table(data, colWidths=[2.5 * inch, 4 * inch])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, separator_row), (-1, separator_row), 1, colors.grey),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.grey),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.grey),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.5 * inch))

    if new_balance > 0:
        elements.append(Paragraph(f"Balance owing: {format_currency(new_balance)}. Please remit payment at your earliest convenience.", normal_center))
    else:
        elements.append(Paragraph("Thank you for your payment!", normal_center))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
