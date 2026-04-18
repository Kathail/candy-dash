"""Purchases blueprint – track supplier purchases."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import Purchase, VALID_PAYMENT_TYPES
from app.helpers import audit, staff_required, admin_required, export_response

bp = Blueprint("purchases", __name__, url_prefix="/purchases")

VALID_SORTS = {"date_asc", "date_desc", "amount_asc", "amount_desc"}
VALID_EXPORT_FORMATS = {"csv", "xlsx", "pdf"}


def _parse_date_params():
    """Parse start_date and end_date from query params as plain dates."""
    start_str = request.args.get("start_date", "").strip()
    end_str = request.args.get("end_date", "").strip()
    start = end = None
    try:
        start = date.fromisoformat(start_str) if start_str else None
    except ValueError:
        start = None
    try:
        end = date.fromisoformat(end_str) if end_str else None
    except ValueError:
        end = None
    if start and end and start > end:
        start, end = end, start
    return start, end


def _build_query(supplier_filter, start_date, end_date, sort):
    """Build the filtered, sorted Purchase query."""
    query = Purchase.query
    if supplier_filter:
        query = query.filter(Purchase.supplier == supplier_filter)
    if start_date:
        query = query.filter(Purchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(Purchase.purchase_date <= end_date)
    if sort == "date_asc":
        query = query.order_by(Purchase.purchase_date.asc(), Purchase.id.asc())
    elif sort == "amount_desc":
        query = query.order_by(Purchase.amount.desc(), Purchase.id.desc())
    elif sort == "amount_asc":
        query = query.order_by(Purchase.amount.asc(), Purchase.id.asc())
    else:
        query = query.order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
    return query


@bp.route("/")
@login_required
def index():
    """List purchases with filtering, sorting, and optional export."""
    supplier_filter = request.args.get("supplier", "").strip()
    sort = request.args.get("sort", "date_desc")
    if sort not in VALID_SORTS:
        sort = "date_desc"
    start_date, end_date = _parse_date_params()

    query = _build_query(supplier_filter, start_date, end_date, sort)

    fmt = request.args.get("format", "").lower()
    if fmt in VALID_EXPORT_FORMATS:
        all_rows = query.all()
        headers = ["Date", "Supplier", "Amount", "Payment Type", "Invoice #", "Description"]
        export_rows = [
            (
                p.purchase_date.strftime("%Y-%m-%d"),
                p.supplier,
                f"{p.amount:.2f}",
                (p.payment_type or "").capitalize(),
                p.invoice_number or "",
                p.description or "",
            )
            for p in all_rows
        ]
        filename = "purchases_export"
        if start_date:
            filename += f"_from_{start_date.strftime('%Y%m%d')}"
        if end_date:
            filename += f"_to_{end_date.strftime('%Y%m%d')}"
        if supplier_filter:
            safe_supplier = re.sub(r"[^\w-]", "_", supplier_filter)[:40]
            filename += f"_{safe_supplier}"
        return export_response(export_rows, headers, filename, fmt, title="Purchases")

    # Aggregates across all matching rows (single round-trip)
    agg = query.with_entities(
        func.coalesce(func.sum(Purchase.amount), 0),
        func.count(Purchase.id),
    ).order_by(None).one()
    total, total_count = agg

    page = max(1, request.args.get("page", 1, type=int))
    pagination = query.paginate(page=page, per_page=10, error_out=False)
    purchases = pagination.items

    # Distinct suppliers for filter
    suppliers = (
        db.session.query(Purchase.supplier)
        .distinct()
        .order_by(Purchase.supplier)
        .all()
    )
    suppliers = [s[0] for s in suppliers]

    return render_template(
        "purchases.html",
        purchases=purchases,
        total=total,
        total_count=total_count,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        start_date=start_date,
        end_date=end_date,
        sort=sort,
        pagination=pagination,
    )


@bp.route("/add", methods=["GET", "POST"])
@login_required
@staff_required
def add():
    """Add a new purchase."""
    if request.method == "POST":
        supplier = request.form.get("supplier", "").strip()
        if not supplier:
            flash("Supplier name is required.", "error")
            return redirect(url_for("purchases.add"))

        try:
            amount = Decimal(request.form.get("amount", "0") or "0")
        except (InvalidOperation, ValueError):
            flash("Invalid amount.", "error")
            return redirect(url_for("purchases.add"))

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return redirect(url_for("purchases.add"))

        purchase_date_str = request.form.get("purchase_date", "")
        try:
            purchase_date = date.fromisoformat(purchase_date_str) if purchase_date_str else date.today()
        except ValueError:
            purchase_date = date.today()

        payment_type = request.form.get("payment_type", "cash").strip() or "cash"
        if payment_type not in VALID_PAYMENT_TYPES:
            payment_type = "other"

        purchase = Purchase(
            supplier=supplier,
            amount=amount,
            purchase_date=purchase_date,
            invoice_number=request.form.get("invoice_number", "").strip() or None,
            description=request.form.get("description", "").strip() or None,
            payment_type=payment_type,
            created_by=current_user.id,
        )
        db.session.add(purchase)
        audit("purchase_added", f"Purchase ${amount:,.2f} from '{supplier}'")
        db.session.commit()

        flash(f"Purchase of ${amount:,.2f} from {supplier} recorded.", "success")
        return redirect(url_for("purchases.index"))

    # GET: render form
    suppliers = (
        db.session.query(Purchase.supplier)
        .distinct()
        .order_by(Purchase.supplier)
        .all()
    )
    suppliers = [s[0] for s in suppliers]
    from app.routes.catalog import CATALOG
    return render_template("purchase_form.html", purchase=None, suppliers=suppliers, catalog=CATALOG)


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@staff_required
def edit(id):
    """Edit a purchase."""
    purchase = Purchase.query.get_or_404(id)

    if request.method == "POST":
        supplier = request.form.get("supplier", "").strip()
        if not supplier:
            flash("Supplier name is required.", "error")
            return render_template("purchase_form.html", purchase=purchase, suppliers=[])

        try:
            amount = Decimal(request.form.get("amount", "0") or "0")
        except (InvalidOperation, ValueError):
            flash("Invalid amount.", "error")
            return render_template("purchase_form.html", purchase=purchase, suppliers=[])

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return render_template("purchase_form.html", purchase=purchase, suppliers=[])

        purchase_date_str = request.form.get("purchase_date", "")
        try:
            purchase.purchase_date = date.fromisoformat(purchase_date_str) if purchase_date_str else date.today()
        except ValueError:
            purchase.purchase_date = date.today()

        purchase.supplier = supplier
        purchase.amount = amount
        purchase.invoice_number = request.form.get("invoice_number", "").strip() or None
        purchase.description = request.form.get("description", "").strip() or None
        pt = request.form.get("payment_type", "cash").strip() or "cash"
        purchase.payment_type = pt if pt in VALID_PAYMENT_TYPES else "other"

        audit("purchase_edited", f"Edited purchase #{purchase.id} from '{supplier}'")
        db.session.commit()

        flash("Purchase updated.", "success")
        return redirect(url_for("purchases.index"))

    suppliers = (
        db.session.query(Purchase.supplier)
        .distinct()
        .order_by(Purchase.supplier)
        .all()
    )
    suppliers = [s[0] for s in suppliers]
    from app.routes.catalog import CATALOG
    return render_template("purchase_form.html", purchase=purchase, suppliers=suppliers, catalog=CATALOG)


@bp.route("/<int:id>/pdf")
@login_required
def pdf(id):
    """Generate a purchase order PDF."""
    import io
    from flask import send_file
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from app.helpers import format_currency, format_date

    purchase = Purchase.query.get_or_404(id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Logo
    import os
    from reportlab.platypus import Image
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "img", "logo.png")
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=1.0 * inch, height=1.0 * inch)
            logo.hAlign = "CENTER"
            elements.append(logo)
            elements.append(Spacer(1, 8))
        except Exception:
            pass

    title_style = ParagraphStyle("POTitle", parent=styles["Heading1"], fontSize=18, alignment=1)
    normal_center = ParagraphStyle("NormalCenter", parent=styles["Normal"], alignment=1)

    elements.append(Paragraph("Northern Sweet Supply", title_style))
    elements.append(Paragraph("Purchase Order", normal_center))
    elements.append(Spacer(1, 0.3 * inch))

    # PO details
    data = [
        ["PO Number:", f"PO-{purchase.id:04d}"],
        ["Date:", format_date(purchase.purchase_date, "%B %d, %Y")],
        ["Supplier:", purchase.supplier],
        ["Payment Type:", (purchase.payment_type or "cash").capitalize()],
    ]
    if purchase.invoice_number:
        data.append(["Invoice #:", purchase.invoice_number])
    data.append(["", ""])
    data.append(["Total Amount:", format_currency(purchase.amount)])

    separator_row = next(i for i, row in enumerate(data) if row == ["", ""])
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

    # Items from description
    if purchase.description:
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("Items:", styles["Heading3"]))
        elements.append(Spacer(1, 0.1 * inch))

        items = [item.strip() for item in purchase.description.split(",") if item.strip()]
        if items:
            item_data = [["#", "Item", "Details"]]
            for i, item in enumerate(items, 1):
                # Try to split "2x Product Name 20x100g" into qty and name
                parts = item.split(" ", 1)
                if parts[0].endswith("x") and parts[0][:-1].isdigit():
                    qty = parts[0]
                    name = parts[1] if len(parts) > 1 else ""
                else:
                    qty = ""
                    name = item
                item_data.append([str(i), name, qty])

            item_table = Table(item_data, colWidths=[0.4 * inch, 4.5 * inch, 1.5 * inch])
            item_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#4b5563")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ]))
            elements.append(item_table)

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(f"Total: {format_currency(purchase.amount)}", ParagraphStyle("Total", parent=styles["Normal"], fontSize=12, fontName="Helvetica-Bold", alignment=2)))

    doc.build(elements)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"PO-{purchase.id:04d}-{re.sub(r'[^\w-]', '_', purchase.supplier)}.pdf",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@admin_required
def delete(id):
    """Delete a purchase."""
    purchase = Purchase.query.get_or_404(id)
    audit("purchase_deleted", f"Deleted purchase #{purchase.id} ${purchase.amount:,.2f} from '{purchase.supplier}'")
    db.session.delete(purchase)
    db.session.commit()
    flash("Purchase deleted.", "success")
    return redirect(url_for("purchases.index"))
