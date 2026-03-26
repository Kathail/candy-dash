"""Analytics dashboard routes with Chart.js data."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template
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


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal values."""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


@bp.route("/")
def index():
    """Analytics dashboard with charts data."""
    today = date.today()

    # --- Revenue over last 12 months (monthly sums) ---
    twelve_months_ago = datetime(
        today.year - 1, today.month, 1, tzinfo=timezone.utc
    )
    monthly_revenue_rows = (
        db.session.query(
            extract("year", Payment.payment_date).label("year"),
            extract("month", Payment.payment_date).label("month"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= twelve_months_ago)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    revenue_labels = []
    revenue_data = []
    for row in monthly_revenue_rows:
        label = date(int(row.year), int(row.month), 1).strftime("%b %Y")
        revenue_labels.append(label)
        revenue_data.append(row.total)

    # --- Collections by city ---
    collections_by_city = (
        db.session.query(
            Customer.city,
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= twelve_months_ago)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .all()
    )
    city_labels = [row.city or "Unknown" for row in collections_by_city]
    city_data = [row.total for row in collections_by_city]

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

    # --- Route efficiency: completed / total stops by week (last 8 weeks) ---
    eight_weeks_ago = today - timedelta(weeks=8)
    weekly_efficiency = (
        db.session.query(
            extract("year", RouteStop.route_date).label("yr"),
            extract("week", RouteStop.route_date).label("wk"),
            func.count(RouteStop.id).label("total"),
            func.sum(
                case((RouteStop.completed.is_(True), 1), else_=0)
            ).label("completed"),
        )
        .filter(RouteStop.route_date >= eight_weeks_ago)
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
    charts_json = json.dumps(charts, cls=_DecimalEncoder)

    return render_template("analytics.html", charts_json=charts_json)
