"""Bookkeeper dashboard — read-only financial overview in one place."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db
from app.helpers import staff_required
from app.models import Customer, Payment, ActivityLog

bp = Blueprint("bookkeeper", __name__, url_prefix="/books")


@bp.before_request
@login_required
@staff_required
def before_request():
    """Require login and non-demo role for bookkeeper routes."""
    pass


@bp.route("/")
def index():
    """All-in-one bookkeeper dashboard."""
    today = date.today()
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    # --- Period selector ---
    period = request.args.get("period", "month")
    if period == "today":
        period_start = day_start
        period_label = "Today"
    elif period == "week":
        dow = today.weekday()
        monday = today - timedelta(days=dow)
        period_start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
        period_label = "This Week"
    elif period == "quarter":
        qm = (today.month - 1) // 3 * 3 + 1
        period_start = datetime(today.year, qm, 1, tzinfo=timezone.utc)
        period_label = "This Quarter"
    else:  # month
        period_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
        period_label = "This Month"

    # --- KPIs ---
    period_payments = (
        db.session.query(
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= period_start)
        .first()
    )
    payment_count = period_payments.count or 0
    payment_total = period_payments.total or Decimal("0")
    avg_payment = round(float(payment_total) / payment_count, 2) if payment_count else 0

    total_outstanding = float(
        db.session.query(func.coalesce(func.sum(Customer.balance), 0))
        .filter(Customer.status == "active")
        .scalar()
    )
    customers_with_balance = Customer.query.filter(
        Customer.status == "active", Customer.balance > 0
    ).count()
    active_customers = Customer.query.filter(Customer.status == "active").count()

    # Today's collections
    today_payments = (
        db.session.query(
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= day_start, Payment.payment_date <= day_end)
        .first()
    )
    today_count = today_payments.count or 0
    today_total = today_payments.total or Decimal("0")

    # --- Paginated transactions ---
    page = request.args.get("page", 1, type=int)
    per_page = 10
    payments_paginated = (
        Payment.query
        .options(joinedload(Payment.customer))
        .join(Customer)
        .order_by(Payment.payment_date.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    # --- Top balances (paginated) ---
    bal_page = request.args.get("bal_page", 1, type=int)
    balances_paginated = (
        Customer.query
        .filter(Customer.status == "active", Customer.balance > 0)
        .order_by(Customer.balance.desc())
        .paginate(page=bal_page, per_page=10, error_out=False)
    )

    # --- Collections by city (paginated) ---
    city_page = request.args.get("city_page", 1, type=int)
    city_per_page = 10
    city_query = (
        db.session.query(
            Customer.city,
            func.sum(Payment.amount).label("total"),
            func.count(Payment.id).label("count"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= period_start)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount).desc())
    )
    city_total_count = city_query.count()
    city_total_pages = max(1, (city_total_count + city_per_page - 1) // city_per_page)
    city_page = min(city_page, city_total_pages)
    city_collections = city_query.offset((city_page - 1) * city_per_page).limit(city_per_page).all()

    # --- Recent activity (paginated) ---
    act_page = request.args.get("act_page", 1, type=int)
    activity_paginated = (
        ActivityLog.query
        .options(joinedload(ActivityLog.customer))
        .join(Customer)
        .filter(ActivityLog.action.in_(("payment_recorded", "payment_deleted", "invoice_paid", "customer_created", "lead_converted")))
        .order_by(ActivityLog.created_at.desc())
        .paginate(page=act_page, per_page=10, error_out=False)
    )

    # Date strings for export links
    start_date = period_start.strftime("%Y-%m-%d")
    end_date = today.isoformat()

    return render_template(
        "bookkeeper.html",
        today=today,
        period=period,
        period_label=period_label,
        start_date=start_date,
        end_date=end_date,
        payment_count=payment_count,
        payment_total=payment_total,
        avg_payment=avg_payment,
        total_outstanding=total_outstanding,
        customers_with_balance=customers_with_balance,
        active_customers=active_customers,
        today_count=today_count,
        today_total=today_total,
        recent_payments=payments_paginated.items,
        payments_pagination=payments_paginated,
        top_balances=balances_paginated.items,
        balances_pagination=balances_paginated,
        city_collections=city_collections,
        city_page=city_page,
        city_total_pages=city_total_pages,
        recent_activity=activity_paginated.items,
        activity_pagination=activity_paginated,
    )
