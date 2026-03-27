"""Dashboard blueprint – daily KPIs and overview."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func, case

from app import db
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

    # Payment KPIs (today)
    payment_stats = db.session.query(
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
    ).filter(
        Payment.payment_date >= day_start, Payment.payment_date <= day_end
    ).first()
    payment_count = payment_stats[0]
    payment_sum = payment_stats[1] or Decimal("0")

    # Yesterday's payments for comparison
    yest_payment = db.session.query(
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
    ).filter(
        Payment.payment_date >= yest_start, Payment.payment_date <= yest_end
    ).scalar() or Decimal("0")

    # Outstanding balance
    total_outstanding = db.session.query(
        func.coalesce(func.sum(Customer.balance), Decimal("0")),
    ).filter(Customer.status == "active").scalar() or Decimal("0")

    # Customer counts
    active_customers = Customer.query.filter(Customer.status == "active").count()
    lead_count = Customer.query.filter(Customer.status == "lead").count()

    # Overdue customers (balance > 0, no payment in 30+ days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    overdue_count = db.session.query(func.count(Customer.id)).filter(
        Customer.status == "active",
        Customer.balance > 0,
    ).scalar() or 0

    # Today's route stops with customer info (for the quick route preview)
    todays_stops = (
        RouteStop.query
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

    # Recent payments (last 5) for the feed
    recent_payments = (
        Payment.query
        .join(Customer)
        .order_by(Payment.payment_date.desc())
        .limit(5)
        .all()
    )

    # Weekly collection trend (last 7 days) — single query
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
    hour = datetime.now().hour
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
        yest_payment=yest_payment,
        total_outstanding=total_outstanding,
        active_customers=active_customers,
        lead_count=lead_count,
        overdue_count=overdue_count,
        todays_stops=todays_stops,
        tomorrow_stops=tomorrow_stops,
        recent_payments=recent_payments,
        week_data=week_data,
    )
