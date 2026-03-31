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


def _compute_aging_buckets(customers):
    """Compute aging bucket labels for a list of customers in a single query."""
    if not customers:
        return {}

    customer_ids = [c.id for c in customers]

    # Get last payment date per customer in one query
    from sqlalchemy import func as sa_func
    last_payments = (
        db.session.query(
            Payment.customer_id,
            sa_func.max(Payment.payment_date).label("last_date"),
        )
        .filter(Payment.customer_id.in_(customer_ids))
        .group_by(Payment.customer_id)
        .all()
    )
    last_payment_map = {row.customer_id: row.last_date for row in last_payments}

    now = datetime.now(timezone.utc)
    result = {}
    for c in customers:
        reference_date = last_payment_map.get(c.id) or c.created_at
        if reference_date is None:
            result[c.id] = "90+"
            continue

        if isinstance(reference_date, date) and not isinstance(reference_date, datetime):
            reference_date = datetime.combine(reference_date, datetime.min.time(), tzinfo=timezone.utc)
        elif isinstance(reference_date, datetime) and reference_date.tzinfo is None:
            reference_date = reference_date.replace(tzinfo=timezone.utc)
        delta = (now - reference_date).days

        if delta <= 30:
            result[c.id] = "0-30"
        elif delta <= 60:
            result[c.id] = "31-60"
        elif delta <= 90:
            result[c.id] = "61-90"
        else:
            result[c.id] = "90+"

    return result


@bp.route("/")
def index():
    """Show customers with outstanding balances, with aging and filters."""
    query = Customer.query.filter(Customer.balance > 0, Customer.status != "deleted")

    # Filter by city
    city_filter = request.args.get("city", "").strip()
    if city_filter:
        query = query.filter(Customer.city == city_filter)

    # Sorting
    sort = request.args.get("sort", "balance_desc")
    if sort == "balance_asc":
        query = query.order_by(Customer.balance.asc())
    elif sort == "name_asc":
        query = query.order_by(Customer.name.asc())
    elif sort == "name_desc":
        query = query.order_by(Customer.name.desc())
    else:
        query = query.order_by(Customer.balance.desc())

    customers = query.all()

    # Compute aging buckets (single query instead of N+1)
    bucket_filter = request.args.get("bucket", "").strip()
    aging_map = _compute_aging_buckets(customers)
    customers_with_aging = []
    for c in customers:
        bucket = aging_map.get(c.id, "90+")
        if bucket_filter and bucket != bucket_filter:
            continue
        customers_with_aging.append({"customer": c, "bucket": bucket})

    # Summary totals
    total_outstanding = sum(
        item["customer"].balance for item in customers_with_aging
    )
    bucket_totals = {}
    bucket_counts = {}
    for item in customers_with_aging:
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
    )


