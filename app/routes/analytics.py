"""Analytics dashboard routes with Chart.js data."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, extract, case

from app import db
from app.models import Customer, Payment, RouteStop

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.before_request
@login_required
def before_request():
    """Require login for all analytics routes."""
    pass


@bp.route("/")
def index():
    """Analytics dashboard with charts data."""
    today = date.today()

    months = request.args.get("months", 12, type=int)
    months = max(1, min(months, 24))
    y = today.year
    m = today.month - months
    while m <= 0:
        m += 12
        y -= 1
    range_start = datetime(y, m, 1, tzinfo=timezone.utc)

    # --- Revenue over selected months (monthly sums) ---
    monthly_revenue_rows = (
        db.session.query(
            extract("year", Payment.payment_date).label("year"),
            extract("month", Payment.payment_date).label("month"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= range_start)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    revenue_labels = []
    revenue_data = []
    for row in monthly_revenue_rows:
        label = date(int(row.year), int(row.month), 1).strftime("%b %Y")
        revenue_labels.append(label)
        revenue_data.append(float(row.total))

    # --- Collections by city ---
    collections_by_city = (
        db.session.query(
            Customer.city,
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= range_start)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .all()
    )
    city_labels = [row.city or "Unknown" for row in collections_by_city]
    city_data = [float(row.total) for row in collections_by_city]

    # --- Customer status distribution ---
    status_dist = (
        db.session.query(
            Customer.status,
            func.count(Customer.id),
        )
        .group_by(Customer.status)
        .all()
    )
    status_labels = [row[0] or "unknown" for row in status_dist]
    status_data = [row[1] for row in status_dist]

    # --- Route efficiency: completed / total stops by week ---
    efficiency_weeks = max(8, months * 4)
    efficiency_start = today - timedelta(weeks=efficiency_weeks)
    weekly_efficiency = (
        db.session.query(
            extract("year", RouteStop.route_date).label("yr"),
            extract("week", RouteStop.route_date).label("wk"),
            func.count(RouteStop.id).label("total"),
            func.sum(
                case((RouteStop.completed.is_(True), 1), else_=0)
            ).label("completed"),
        )
        .filter(RouteStop.route_date >= efficiency_start)
        .group_by("yr", "wk")
        .order_by("yr", "wk")
        .all()
    )

    efficiency_labels = [f"{int(row.yr)}-W{int(row.wk):02d}" for row in weekly_efficiency]
    efficiency_total = [row.total for row in weekly_efficiency]
    efficiency_completed = [int(row.completed) for row in weekly_efficiency]

    # Serialize all chart data as JSON
    charts = {
        "revenue": {
            "labels": revenue_labels,
            "data": revenue_data,
        },
        "collections_by_city": {
            "labels": city_labels,
            "data": city_data,
        },
        "status_distribution": {
            "labels": status_labels,
            "data": status_data,
        },
        "route_efficiency": {
            "labels": efficiency_labels,
            "total": efficiency_total,
            "completed": efficiency_completed,
        },
    }
    # KPI summaries for the selected period
    total_revenue = sum(revenue_data) if revenue_data else Decimal("0")
    total_payments = db.session.query(func.count(Payment.id)).filter(
        Payment.payment_date >= range_start
    ).scalar() or 0
    active_customers = Customer.query.filter(Customer.status == "active").count()
    total_stops = sum(efficiency_total) if efficiency_total else 0
    completed_stops = sum(efficiency_completed) if efficiency_completed else 0
    completion_rate = round(completed_stops / total_stops * 100) if total_stops else 0

    return render_template(
        "analytics.html",
        charts=charts,
        months=months,
        total_revenue=total_revenue,
        total_payments=total_payments,
        active_customers=active_customers,
        completion_rate=completion_rate,
    )
