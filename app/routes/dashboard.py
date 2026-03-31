"""Dashboard blueprint – daily KPIs and overview."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db
from app.helpers import TZ_DISPLAY
from app.models import Customer, RouteStop, Payment

bp = Blueprint("dashboard", __name__, url_prefix="")


@bp.route("/")
@login_required
def index():
    """Landing page with today's KPIs and quick actions."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    yest_start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
    yest_end = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    # Route-stop KPIs
    total_stops = RouteStop.query.filter(RouteStop.route_date == today).count()
    completed_stops = RouteStop.query.filter(
        RouteStop.route_date == today, RouteStop.completed.is_(True)
    ).count()

    # Payment KPIs (today) — count, sum, and max in a single query
    payment_stats = db.session.query(
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
        func.coalesce(func.max(Payment.amount), Decimal("0")),
        func.coalesce(func.sum(Payment.amount_sold), Decimal("0")),
        func.sum(db.case((Payment.amount > 0, 1), else_=0)),
        func.sum(db.case((Payment.amount_sold > 0, 1), else_=0)),
    ).filter(
        Payment.payment_date >= day_start, Payment.payment_date <= day_end
    ).first()
    payment_count = payment_stats[0]
    payment_sum = payment_stats[1] or Decimal("0")
    highest_today = payment_stats[2] or Decimal("0")
    sales_sum = payment_stats[3] or Decimal("0")
    collection_count = int(payment_stats[4] or 0)
    sales_count = int(payment_stats[5] or 0)

    # Today's avg order value
    avg_order_today = round(float(payment_sum) / collection_count, 2) if collection_count else 0

    # Yesterday's payments for comparison
    yest_payment = db.session.query(
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
    ).filter(
        Payment.payment_date >= yest_start, Payment.payment_date <= yest_end
    ).scalar() or Decimal("0")

    # Outstanding balance — only customers on today's route
    total_outstanding = db.session.query(
        func.coalesce(func.sum(Customer.balance), Decimal("0")),
    ).join(RouteStop, RouteStop.customer_id == Customer.id).filter(
        Customer.status == "active",
        Customer.balance > 0,
        RouteStop.route_date == today,
    ).scalar() or Decimal("0")

    # Customer counts
    active_customers = Customer.query.filter(Customer.status == "active").count()
    lead_count = Customer.query.filter(Customer.status == "lead").count()

    # Overdue customers on today's route (balance > 0)
    overdue_count = db.session.query(func.count(Customer.id)).join(
        RouteStop, RouteStop.customer_id == Customer.id
    ).filter(
        Customer.status == "active",
        Customer.balance > 0,
        RouteStop.route_date == today,
    ).scalar() or 0

    # Today's route stops with customer info
    todays_stops = (
        RouteStop.query
        .options(joinedload(RouteStop.customer))
        .join(Customer)
        .filter(RouteStop.route_date == today)
        .order_by(RouteStop.sequence)
        .limit(5)
        .all()
    )

    # Tomorrow's stop count
    tomorrow_stops = RouteStop.query.filter(
        RouteStop.route_date == today + timedelta(days=1)
    ).count()

    # This week's schedule (remaining days)
    week_end = today + timedelta(days=(6 - today.weekday()))  # through Sunday
    week_schedule = (
        db.session.query(
            RouteStop.route_date,
            func.count(RouteStop.id).label("total"),
            func.sum(
                db.case((RouteStop.completed.is_(True), 1), else_=0)
            ).label("completed"),
        )
        .filter(
            RouteStop.route_date >= today,
            RouteStop.route_date <= week_end,
        )
        .group_by(RouteStop.route_date)
        .order_by(RouteStop.route_date)
        .all()
    )
    week_schedule_data = [
        {
            "date": row.route_date,
            "day": row.route_date.strftime("%a"),
            "total": row.total,
            "completed": int(row.completed),
            "is_today": row.route_date == today,
        }
        for row in week_schedule
    ]

    # Needs attention: active customers not visited in 30+ days (top 5)
    from app.helpers import get_needs_attention
    attention_list = get_needs_attention(limit=5)

    # Top balances (top 5 customers with highest balance)
    top_balances = (
        Customer.query
        .filter(Customer.status == "active", Customer.balance > 0)
        .order_by(Customer.balance.desc())
        .limit(5)
        .all()
    )

    # Weekly collection trend (last 7 days)
    week_start = today - timedelta(days=6)
    week_start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)

    daily_totals_rows = (
        db.session.query(
            func.date(Payment.payment_date).label("pay_date"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= week_start_dt)
        .group_by(func.date(Payment.payment_date))
        .all()
    )
    daily_totals_map = {str(row.pay_date): float(row.total) for row in daily_totals_rows}

    week_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        week_data.append({
            "day": d.strftime("%a"),
            "date": d.isoformat(),
            "total": daily_totals_map.get(d.isoformat(), 0.0),
        })

    # Greeting based on time of day
    hour = datetime.now(TZ_DISPLAY).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    return render_template(
        "dashboard.html",
        today=today,
        greeting=greeting,
        total_stops=total_stops,
        completed_stops=completed_stops,
        payment_count=payment_count,
        payment_sum=payment_sum,
        sales_sum=sales_sum,
        collection_count=collection_count,
        sales_count=sales_count,
        highest_today=highest_today,
        avg_order_today=avg_order_today,
        yest_payment=yest_payment,
        total_outstanding=total_outstanding,
        active_customers=active_customers,
        lead_count=lead_count,
        overdue_count=overdue_count,
        todays_stops=todays_stops,
        tomorrow_stops=tomorrow_stops,
        week_schedule=week_schedule_data,
        attention_list=attention_list,
        top_balances=top_balances,
        week_data=week_data,
    )
