"""Outstanding balances management routes."""

from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models import Customer, Payment

bp = Blueprint("balances", __name__, url_prefix="/balances")


@bp.before_request
@login_required
def before_request():
    """Require login for all balance routes."""
    pass


def _aging_bucket(reference_date):
    """Return aging bucket label for a reference date."""
    now = datetime.now(timezone.utc)
    if reference_date is None:
        return "90+"
    if isinstance(reference_date, date) and not isinstance(reference_date, datetime):
        reference_date = datetime.combine(reference_date, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(reference_date, datetime) and reference_date.tzinfo is None:
        reference_date = reference_date.replace(tzinfo=timezone.utc)
    delta = (now - reference_date).days
    if delta <= 30:
        return "0-30"
    elif delta <= 60:
        return "31-60"
    elif delta <= 90:
        return "61-90"
    return "90+"


@bp.route("/")
def index():
    """Show customers with outstanding balances, with aging and filters."""
    city_filter = request.args.get("city", "").strip()
    sort = request.args.get("sort", "balance_desc")
    bucket_filter = request.args.get("bucket", "").strip()

    # Single query: customers + last payment date via LEFT JOIN subquery
    last_pay = (
        db.session.query(
            Payment.customer_id,
            func.max(Payment.payment_date).label("last_date"),
        )
        .group_by(Payment.customer_id)
        .subquery()
    )

    query = (
        db.session.query(Customer, last_pay.c.last_date)
        .outerjoin(last_pay, Customer.id == last_pay.c.customer_id)
        .filter(Customer.balance > 0, Customer.status != "deleted")
    )

    if city_filter:
        query = query.filter(Customer.city == city_filter)

    if sort == "balance_asc":
        query = query.order_by(Customer.balance.asc())
    elif sort == "name_asc":
        query = query.order_by(Customer.name.asc())
    elif sort == "name_desc":
        query = query.order_by(Customer.name.desc())
    else:
        query = query.order_by(Customer.balance.desc())

    rows = query.all()

    all_with_aging = []
    for customer, last_date in rows:
        bucket = _aging_bucket(last_date or customer.created_at)
        if bucket_filter and bucket != bucket_filter:
            continue
        all_with_aging.append({"customer": customer, "bucket": bucket})

    # Manual pagination (query uses session.query, not Model.query)
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total_items = len(all_with_aging)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    customers_with_aging = all_with_aging[start:start + per_page]

    # Summary totals (across ALL items, not just current page)
    total_outstanding = sum(
        item["customer"].balance for item in all_with_aging
    )
    bucket_totals = {}
    bucket_counts = {}
    for item in all_with_aging:
        b = item["bucket"]
        bucket_totals[b] = bucket_totals.get(b, Decimal("0")) + item["customer"].balance
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

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
    # Support HTMX partial rendering
    if request.headers.get("HX-Request"):
        template = "partials/balances_table.html"

    return render_template(
        template,
        customers=customers_with_aging,
        total_outstanding=total_outstanding,
        bucket_totals=bucket_totals,
        customers_with_aging_counts=bucket_counts,
        cities=cities,
        city_filter=city_filter,
        bucket_filter=bucket_filter,
        sort=sort,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
    )


