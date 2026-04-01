"""Purchases blueprint – track supplier purchases."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import Purchase
from app.helpers import audit

bp = Blueprint("purchases", __name__, url_prefix="/purchases")


@bp.route("/")
@login_required
def index():
    """List purchases with filtering."""
    supplier_filter = request.args.get("supplier", "").strip()
    month_filter = request.args.get("month", "").strip()
    sort = request.args.get("sort", "date_desc")

    query = Purchase.query

    if supplier_filter:
        query = query.filter(Purchase.supplier == supplier_filter)

    if month_filter:
        try:
            year, month = month_filter.split("-")
            query = query.filter(
                db.extract("year", Purchase.purchase_date) == int(year),
                db.extract("month", Purchase.purchase_date) == int(month),
            )
        except (ValueError, AttributeError):
            pass

    if sort == "date_asc":
        query = query.order_by(Purchase.purchase_date.asc())
    elif sort == "amount_desc":
        query = query.order_by(Purchase.amount.desc())
    elif sort == "amount_asc":
        query = query.order_by(Purchase.amount.asc())
    else:
        query = query.order_by(Purchase.purchase_date.desc())

    # Total across all matching (separate query with same filters, before pagination)
    total_query = Purchase.query
    if supplier_filter:
        total_query = total_query.filter(Purchase.supplier == supplier_filter)
    if month_filter:
        try:
            year, month = month_filter.split("-")
            total_query = total_query.filter(
                db.extract("year", Purchase.purchase_date) == int(year),
                db.extract("month", Purchase.purchase_date) == int(month),
            )
        except (ValueError, AttributeError):
            pass
    total = db.session.query(func.coalesce(func.sum(Purchase.amount), 0)).filter(
        Purchase.id.in_(total_query.with_entities(Purchase.id))
    ).scalar()

    page = request.args.get("page", 1, type=int)
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

    # Available months for filter
    months = (
        db.session.query(
            db.extract("year", Purchase.purchase_date).label("y"),
            db.extract("month", Purchase.purchase_date).label("m"),
        )
        .distinct()
        .order_by(db.text("y DESC, m DESC"))
        .all()
    )
    month_options = [f"{int(r.y)}-{int(r.m):02d}" for r in months]

    return render_template(
        "purchases.html",
        purchases=purchases,
        total=total,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        month_filter=month_filter,
        month_options=month_options,
        sort=sort,
        pagination=pagination,
    )


@bp.route("/add", methods=["GET", "POST"])
@login_required
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

        purchase = Purchase(
            supplier=supplier,
            amount=amount,
            purchase_date=purchase_date,
            invoice_number=request.form.get("invoice_number", "").strip() or None,
            description=request.form.get("description", "").strip() or None,
            payment_type=request.form.get("payment_type", "cash").strip() or "cash",
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
    return render_template("purchase_form.html", purchase=None, suppliers=suppliers)


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
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
        purchase.payment_type = request.form.get("payment_type", "cash").strip() or "cash"

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
    return render_template("purchase_form.html", purchase=purchase, suppliers=suppliers)


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    """Delete a purchase."""
    purchase = Purchase.query.get_or_404(id)
    audit("purchase_deleted", f"Deleted purchase #{purchase.id} ${purchase.amount:,.2f} from '{purchase.supplier}'")
    db.session.delete(purchase)
    db.session.commit()
    flash("Purchase deleted.", "success")
    return redirect(url_for("purchases.index"))
