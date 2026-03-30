"""Bookkeeper dashboard — read-only financial overview in one place."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import Customer, Payment, ActivityLog

bp = Blueprint("bookkeeper", __name__, url_prefix="/books")


@bp.before_request
@login_required
def before_request():
    """Require login for bookkeeper routes."""
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

    # --- Recent payments (last 20) ---
    recent_payments = (
        Payment.query
        .join(Customer)
        .order_by(Payment.payment_date.desc())
        .limit(20)
        .all()
    )

    # --- Top balances (all with balance > 0) ---
    top_balances = (
        Customer.query
        .filter(Customer.status == "active", Customer.balance > 0)
        .order_by(Customer.balance.desc())
        .limit(15)
        .all()
    )

    # --- Collections by city (for the period) ---
    city_collections = (
        db.session.query(
            Customer.city,
            func.sum(Payment.amount).label("total"),
            func.count(Payment.id).label("count"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= period_start)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .all()
    )

    # --- Recent activity (last 15 financial actions) ---
    recent_activity = (
        ActivityLog.query
        .join(Customer)
        .filter(ActivityLog.action.in_(("payment_recorded", "payment_deleted", "customer_created", "lead_converted")))
        .order_by(ActivityLog.created_at.desc())
        .limit(15)
        .all()
    )

    return render_template(
        "bookkeeper.html",
        today=today,
        period=period,
        period_label=period_label,
        payment_count=payment_count,
        payment_total=payment_total,
        avg_payment=avg_payment,
        total_outstanding=total_outstanding,
        customers_with_balance=customers_with_balance,
        active_customers=active_customers,
        today_count=today_count,
        today_total=today_total,
        recent_payments=recent_payments,
        top_balances=top_balances,
        city_collections=city_collections,
        recent_activity=recent_activity,
    )
