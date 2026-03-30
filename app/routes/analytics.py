"""Analytics dashboard routes with Chart.js data."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, extract, case

from app import db
from app.models import Customer, Payment, RouteStop, ActivityLog

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

    # Previous period (same duration, immediately before)
    prev_y = y
    prev_m = m - months
    while prev_m <= 0:
        prev_m += 12
        prev_y -= 1
    prev_range_start = datetime(prev_y, prev_m, 1, tzinfo=timezone.utc)

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

    # Previous period revenue (for overlay)
    prev_revenue_rows = (
        db.session.query(
            extract("year", Payment.payment_date).label("year"),
            extract("month", Payment.payment_date).label("month"),
            func.coalesce(func.sum(Payment.amount), Decimal("0")).label("total"),
        )
        .filter(
            Payment.payment_date >= prev_range_start,
            Payment.payment_date < range_start,
        )
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )
    prev_revenue_data = [float(row.total) for row in prev_revenue_rows]

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
    total_customer_count = sum(status_data)

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

    # --- KPI: Totals for current and previous periods ---
    total_revenue = sum(revenue_data) if revenue_data else 0
    prev_total_revenue = sum(prev_revenue_data) if prev_revenue_data else 0

    total_payments = db.session.query(func.count(Payment.id)).filter(
        Payment.payment_date >= range_start
    ).scalar() or 0
    prev_total_payments = db.session.query(func.count(Payment.id)).filter(
        Payment.payment_date >= prev_range_start,
        Payment.payment_date < range_start,
    ).scalar() or 0

    avg_order_value = round(total_revenue / total_payments, 2) if total_payments else 0
    prev_avg_order = round(prev_total_revenue / prev_total_payments, 2) if prev_total_payments else 0

    active_customers = Customer.query.filter(Customer.status == "active").count()

    total_stops = sum(efficiency_total) if efficiency_total else 0
    completed_stops = sum(efficiency_completed) if efficiency_completed else 0
    completion_rate = round(completed_stops / total_stops * 100) if total_stops else 0

    total_outstanding = float(
        db.session.query(func.coalesce(func.sum(Customer.balance), 0))
        .filter(Customer.status == "active")
        .scalar()
    )
    customers_with_balance = (
        Customer.query.filter(Customer.status == "active", Customer.balance > 0).count()
    )

    # --- Top stores by revenue ---
    top_stores_rows = (
        db.session.query(
            Customer.id,
            Customer.name,
            Customer.city,
            func.sum(Payment.amount).label("revenue"),
            func.count(Payment.id).label("payment_count"),
            func.avg(Payment.amount).label("avg_payment"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= range_start)
        .group_by(Customer.id, Customer.name, Customer.city)
        .order_by(func.sum(Payment.amount).desc())
        .limit(10)
        .all()
    )

    # Get last visit for top stores
    top_store_ids = [r.id for r in top_stores_rows]
    last_visit_map = {}
    if top_store_ids:
        visit_rows = (
            db.session.query(
                RouteStop.customer_id,
                func.max(RouteStop.route_date).label("last_date"),
            )
            .filter(
                RouteStop.customer_id.in_(top_store_ids),
                RouteStop.completed.is_(True),
            )
            .group_by(RouteStop.customer_id)
            .all()
        )
        last_visit_map = {r.customer_id: r.last_date for r in visit_rows}

    top_stores = [
        {
            "id": r.id,
            "name": r.name,
            "city": r.city or "—",
            "revenue": float(r.revenue),
            "payment_count": r.payment_count,
            "avg_payment": float(r.avg_payment or 0),
            "last_visit": last_visit_map.get(r.id),
        }
        for r in top_stores_rows
    ]

    # --- Needs attention: active customers not visited in 30+ days ---
    subq = (
        db.session.query(
            RouteStop.customer_id,
            func.max(RouteStop.route_date).label("last_visit"),
        )
        .filter(RouteStop.completed.is_(True))
        .group_by(RouteStop.customer_id)
        .subquery()
    )

    needs_attention = (
        db.session.query(
            Customer.id,
            Customer.name,
            Customer.city,
            Customer.balance,
            subq.c.last_visit,
        )
        .outerjoin(subq, Customer.id == subq.c.customer_id)
        .filter(Customer.status == "active")
        .filter(
            db.or_(
                subq.c.last_visit.is_(None),
                subq.c.last_visit < today - timedelta(days=30),
            )
        )
        .order_by(subq.c.last_visit.asc().nullsfirst())
        .limit(10)
        .all()
    )

    attention_list = [
        {
            "id": r.id,
            "name": r.name,
            "city": r.city or "—",
            "balance": float(r.balance or 0),
            "last_visit": r.last_visit,
            "days_since": (today - r.last_visit).days if r.last_visit else None,
        }
        for r in needs_attention
    ]

    # --- Best collection days (day of week averages) ---
    # Use extract('dow') for Postgres (0=Sun), strftime for SQLite
    try:
        dow_rows = (
            db.session.query(
                extract("isodow", Payment.payment_date).label("dow"),
                func.avg(Payment.amount).label("avg_amount"),
                func.count(Payment.id).label("count"),
            )
            .filter(Payment.payment_date >= range_start)
            .group_by("dow")
            .order_by("dow")
            .all()
        )
    except Exception:
        db.session.rollback()
        dow_rows = []

    dow_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    day_of_week_labels = [dow_names.get(int(r.dow), "?") for r in dow_rows]
    day_of_week_data = [float(r.avg_amount or 0) for r in dow_rows]

    # --- Balance stats ---
    highest_balance_row = (
        Customer.query
        .filter(Customer.status == "active", Customer.balance > 0)
        .order_by(Customer.balance.desc())
        .first()
    )
    balance_stats = {
        "total": total_outstanding,
        "count": customers_with_balance,
        "average": round(total_outstanding / customers_with_balance, 2) if customers_with_balance else 0,
        "highest_amount": float(highest_balance_row.balance) if highest_balance_row else 0,
        "highest_id": highest_balance_row.id if highest_balance_row else None,
        "highest_name": highest_balance_row.name if highest_balance_row else None,
    }

    # Serialize chart data
    charts = {
        "revenue": {
            "labels": revenue_labels,
            "data": revenue_data,
            "prev_data": prev_revenue_data,
        },
        "collections_by_city": {
            "labels": city_labels,
            "data": city_data,
        },
        "status_distribution": {
            "labels": status_labels,
            "data": status_data,
            "total": total_customer_count,
        },
        "route_efficiency": {
            "labels": efficiency_labels,
            "total": efficiency_total,
            "completed": efficiency_completed,
        },
        "day_of_week": {
            "labels": day_of_week_labels,
            "data": day_of_week_data,
        },
    }

    # Delta helpers
    def pct_change(current, previous):
        if not previous:
            return None
        return round((current - previous) / previous * 100)

    return render_template(
        "analytics.html",
        charts=charts,
        months=months,
        total_revenue=total_revenue,
        prev_total_revenue=prev_total_revenue,
        revenue_delta=pct_change(total_revenue, prev_total_revenue),
        total_payments=total_payments,
        prev_total_payments=prev_total_payments,
        payments_delta=pct_change(total_payments, prev_total_payments),
        avg_order_value=avg_order_value,
        avg_order_delta=pct_change(avg_order_value, prev_avg_order),
        active_customers=active_customers,
        completion_rate=completion_rate,
        total_outstanding=total_outstanding,
        balance_stats=balance_stats,
        top_stores=top_stores,
        attention_list=attention_list,
        today=today,
    )
