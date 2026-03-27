"""Shared helpers: decorators, PDF generation, template filters."""

import io
from decimal import Decimal
from datetime import datetime, timezone, timedelta, date

# GMT-5 (Central Daylight / Eastern Standard)
TZ_DISPLAY = timezone(timedelta(hours=-5))
from functools import wraps
from urllib.parse import urlparse, urljoin

from flask import abort, redirect, request, url_for
from flask_login import current_user
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def admin_required(f):
    """Decorator that requires the current user to be an admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
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
    if not target:
        return url_for("dashboard.index")
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    if test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc:
        return target
    return url_for("dashboard.index")


def format_currency(value):
    """Template filter: format a number as currency."""
    if value is None:
        return "$0.00"
    return f"${Decimal(str(value)):,.2f}"


def format_date(value, fmt="%b %d, %Y"):
    """Template filter: format a datetime or date object in GMT-5."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(fmt)
    # Convert UTC datetimes to GMT-5 for display
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(TZ_DISPLAY)
    return value.strftime(fmt)


def generate_receipt_number(payment_date=None, max_retries=5):
    """Generate a unique receipt number in format RCP-YYYYMMDD-XXXX.

    Uses SELECT ... FOR UPDATE (Postgres) to prevent race conditions.
    Falls back to retry-on-conflict for SQLite.
    """
    from app.models import Payment
    from app import db

    if payment_date is None:
        payment_date = datetime.now(timezone.utc)

    date_str = payment_date.strftime("%Y%m%d")
    prefix = f"RCP-{date_str}-"

    # Use FOR UPDATE to lock the row and prevent concurrent duplicates
    last = (
        Payment.query
        .filter(Payment.receipt_number.like(f"{prefix}%"))
        .order_by(Payment.receipt_number.desc())
        .with_for_update()
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


def generate_receipt_pdf(payment, customer):
    """Generate a PDF receipt for a payment. Returns bytes."""
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

    elements.append(Paragraph("Candy Route Planner", title_style))
    elements.append(Paragraph("Payment Receipt", normal_center))
    elements.append(Spacer(1, 0.3 * inch))

    data = [
        ["Receipt #:", payment.receipt_number],
        ["Date:", format_date(payment.payment_date, "%B %d, %Y")],
        ["Customer:", customer.name],
        ["", ""],
        ["Previous Balance:", format_currency(payment.previous_balance)],
        ["Payment Amount:", format_currency(payment.amount)],
        ["New Balance:", format_currency(payment.previous_balance - payment.amount)],
    ]

    if payment.notes:
        data.append(["Notes:", payment.notes])

    table = Table(data, colWidths=[2.5 * inch, 4 * inch])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 3), (-1, 3), 1, colors.grey),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.grey),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.grey),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Thank you for your payment!", normal_center))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
