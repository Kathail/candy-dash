"""Outstanding balances management routes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import case, func

from app import db
from app.models import Customer, Invoice, Payment, VALID_PAYMENT_TYPES

bp = Blueprint("balances", __name__, url_prefix="/balances")


@bp.before_request
@login_required
def before_request():
    """Require login for all balance routes."""
    pass


@bp.route("/")
def index():
    """Show customers with outstanding balances, with aging and filters."""
    city_filter = request.args.get("city", "").strip()
    sort = request.args.get("sort", "balance_desc")
    bucket_filter = request.args.get("bucket", "").strip()
    q = request.args.get("q", "").strip()
    payment_type_filter = request.args.get("payment_type", "").strip()
    if payment_type_filter and payment_type_filter not in VALID_PAYMENT_TYPES:
        payment_type_filter = ""

    # Subquery: oldest unpaid invoice date per customer (standard aging basis)
    oldest_unpaid = (
        db.session.query(
            Invoice.customer_id,
            func.min(Invoice.invoice_date).label("oldest_date"),
        )
        .filter(Invoice.status == "unpaid")
        .group_by(Invoice.customer_id)
        .subquery()
    )

    # Fallback: last payment date per customer
    last_pay = (
        db.session.query(
            Payment.customer_id,
            func.max(Payment.payment_date).label("last_date"),
        )
        .group_by(Payment.customer_id)
        .subquery()
    )

    # Aging bucket: prefer oldest unpaid invoice date, fallback to last payment, then created_at
    now = datetime.now(timezone.utc)
    ref_date = func.coalesce(oldest_unpaid.c.oldest_date, last_pay.c.last_date, Customer.created_at)
    bucket_expr = case(
        (ref_date.is_(None), "90+"),
        (ref_date < now - timedelta(days=90), "90+"),
        (ref_date < now - timedelta(days=60), "61-90"),
        (ref_date < now - timedelta(days=30), "31-60"),
        else_="0-30",
    )

    # Subquery: customers who have at least one payment of a given type
    if payment_type_filter:
        customers_with_ptype = (
            db.session.query(Payment.customer_id)
            .filter(Payment.payment_type == payment_type_filter)
            .distinct()
            .subquery()
        )

    # Base filters (applied to both summary and list)
    base_filters = [Customer.balance > 0, Customer.status != "deleted"]
    if city_filter:
        base_filters.append(Customer.city == city_filter)
    if q:
        base_filters.append(db.or_(
            Customer.name.ilike(f"%{q}%"),
            Customer.customer_code.ilike(f"%{q}%"),
        ))
    if payment_type_filter:
        base_filters.append(Customer.id.in_(db.session.query(customers_with_ptype.c.customer_id)))

    # Bucket summary (unfiltered by bucket so all buckets always show totals)
    bucket_rows = (
        db.session.query(
            bucket_expr.label("bucket"),
            func.sum(Customer.balance).label("total"),
            func.count().label("count"),
        )
        .outerjoin(oldest_unpaid, Customer.id == oldest_unpaid.c.customer_id)
        .outerjoin(last_pay, Customer.id == last_pay.c.customer_id)
        .filter(*base_filters)
        .group_by(bucket_expr)
        .all()
    )

    bucket_totals = {r.bucket: r.total for r in bucket_rows}
    bucket_counts = {r.bucket: r.count for r in bucket_rows}
    total_outstanding = sum((r.total for r in bucket_rows), Decimal("0"))

    # Customer list query
    query = (
        db.session.query(Customer, bucket_expr.label("bucket"))
        .outerjoin(oldest_unpaid, Customer.id == oldest_unpaid.c.customer_id)
        .outerjoin(last_pay, Customer.id == last_pay.c.customer_id)
        .filter(*base_filters)
    )

    if bucket_filter:
        query = query.filter(bucket_expr == bucket_filter)
        total_items = bucket_counts.get(bucket_filter, 0)
    else:
        total_items = sum(r.count for r in bucket_rows)

    if sort == "balance_asc":
        query = query.order_by(Customer.balance.asc())
    elif sort == "name_asc":
        query = query.order_by(Customer.name.asc())
    elif sort == "name_desc":
        query = query.order_by(Customer.name.desc())
    else:
        query = query.order_by(Customer.balance.desc())

    # Paginate (SQL-level)
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = min(page, total_pages)
    results = query.offset((page - 1) * per_page).limit(per_page).all()

    customers_with_aging = [{"customer": r[0], "bucket": r[1]} for r in results]

    # Available cities for the filter dropdown
    cities = (
        db.session.query(Customer.city)
        .filter(Customer.balance > 0, Customer.city.isnot(None), Customer.city != "")
        .distinct()
        .order_by(Customer.city)
        .all()
    )
    cities = [c[0] for c in cities]

    template = "balances.html"
    if request.headers.get("HX-Request"):
        template = "partials/balance_rows.html"

    payment_types = ["cash", "cheque", "debit", "credit", "etransfer", "scholtens", "other"]

    return render_template(
        template,
        customers=customers_with_aging,
        total_outstanding=total_outstanding,
        bucket_totals=bucket_totals,
        customers_with_aging_counts=bucket_counts,
        cities=cities,
        city_filter=city_filter,
        bucket_filter=bucket_filter,
        payment_type_filter=payment_type_filter,
        payment_types=payment_types,
        sort=sort,
        q=q,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
    )
