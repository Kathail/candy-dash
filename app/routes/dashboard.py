"""Dashboard blueprint – daily KPIs and overview."""

from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import Customer, RouteStop, Payment, ActivityLog

bp = Blueprint("dashboard", __name__, url_prefix="")


@bp.route("/")
@login_required
def index():
    """Landing page with today's KPIs."""
    today = date.today()
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    day_end = datetime(
        today.year, today.month, today.day, 23, 59, 59, 999999,
        tzinfo=timezone.utc,
    )

    # Route-stop KPIs
    total_stops = RouteStop.query.filter(RouteStop.route_date == today).count()
    completed_stops = RouteStop.query.filter(
        RouteStop.route_date == today,
        RouteStop.completed.is_(True),
    ).count()

    # Payment KPIs
    payment_stats = db.session.query(
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount), Decimal("0")),
    ).filter(
        Payment.payment_date >= day_start,
        Payment.payment_date <= day_end,
    ).first()
    payment_count = payment_stats[0]
    payment_sum = payment_stats[1] or Decimal("0")

    # Outstanding balance across all active customers
    total_outstanding = db.session.query(
        func.coalesce(func.sum(Customer.balance), Decimal("0")),
    ).filter(Customer.status == "active").scalar() or Decimal("0")

    # Recent activity (last 20 entries)
    recent_activity = (
        ActivityLog.query
        .order_by(ActivityLog.created_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "dashboard.html",
        today=today,
        total_stops=total_stops,
        completed_stops=completed_stops,
        payment_count=payment_count,
        payment_sum=payment_sum,
        total_outstanding=total_outstanding,
        recent_activity=recent_activity,
    )
