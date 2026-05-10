"""Analytics dashboard routes with Chart.js data."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, extract, case

from app import db
from app.models import Customer, Payment, RouteStop, ActivityLog, Purchase

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
            func.coalesce(func.sum(Payment.amount_sold), Decimal("0")).label("total"),
        )
        .filter(Payment.payment_date >= range_start)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    revenue_labels = []
    revenue_data = []
    revenue_month_keys = []
    for row in monthly_revenue_rows:
        y_, m_ = int(row.year), int(row.month)
        revenue_labels.append(date(y_, m_, 1).strftime("%b %Y"))
        revenue_data.append(float(row.total))
        revenue_month_keys.append((y_, m_))

    # --- Purchases / cost over the same period (for profit + cash flow) ---
    range_start_d = range_start.date()
    prev_range_start_d = prev_range_start.date()

    monthly_purchase_rows = (
        db.session.query(
            extract("year", Purchase.purchase_date).label("year"),
            extract("month", Purchase.purchase_date).label("month"),
            func.coalesce(func.sum(Purchase.amount), Decimal("0")).label("total"),
        )
        .filter(Purchase.purchase_date >= range_start_d)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )
    purchase_map = {(int(r.year), int(r.month)): float(r.total) for r in monthly_purchase_rows}
    # Align with revenue's month buckets so the two series share the same x-axis.
    # Also fill in any month buckets where there were purchases but no revenue.
    all_keys = sorted(set(revenue_month_keys) | set(purchase_map.keys()))
    cashflow_labels = [date(y, m, 1).strftime("%b %Y") for (y, m) in all_keys]
    revenue_aligned = [
        revenue_data[revenue_month_keys.index((y, m))] if (y, m) in revenue_month_keys else 0
        for (y, m) in all_keys
    ]
    purchase_aligned = [purchase_map.get((y, m), 0) for (y, m) in all_keys]

    total_purchases = float(
        db.session.query(func.coalesce(func.sum(Purchase.amount), Decimal("0")))
        .filter(Purchase.purchase_date >= range_start_d)
        .scalar() or 0
    )
    prev_total_purchases = float(
        db.session.query(func.coalesce(func.sum(Purchase.amount), Decimal("0")))
        .filter(
            Purchase.purchase_date >= prev_range_start_d,
            Purchase.purchase_date < range_start_d,
        )
        .scalar() or 0
    )

    # profit/margin computed below, after total_revenue is available

    # --- Top suppliers by spend ---
    top_supplier_rows = (
        db.session.query(
            Purchase.supplier,
            func.coalesce(func.sum(Purchase.amount), Decimal("0")).label("total"),
            func.count(Purchase.id).label("count"),
        )
        .filter(Purchase.purchase_date >= range_start_d)
        .group_by(Purchase.supplier)
        .order_by(func.sum(Purchase.amount).desc())
        .limit(5)
        .all()
    )
    top_suppliers = [
        {"name": r.supplier, "total": float(r.total), "count": r.count}
        for r in top_supplier_rows
    ]

    # Previous period revenue (for overlay)
    prev_revenue_rows = (
        db.session.query(
            extract("year", Payment.payment_date).label("year"),
            extract("month", Payment.payment_date).label("month"),
            func.coalesce(func.sum(Payment.amount_sold), Decimal("0")).label("total"),
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

    # --- Sales by city ---
    collections_by_city = (
        db.session.query(
            Customer.city,
            func.coalesce(func.sum(Payment.amount_sold), Decimal("0")).label("total"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= range_start)
        .group_by(Customer.city)
        .order_by(func.sum(Payment.amount_sold).desc())
        .all()
    )
    city_labels = [row.city or "Unknown" for row in collections_by_city]
    city_data = [float(row.total) for row in collections_by_city]

    # --- Active customer count per city (for city leaderboard) ---
    city_customer_counts = dict(
        db.session.query(Customer.city, func.count(Customer.id))
        .filter(Customer.status != "deleted")
        .group_by(Customer.city)
        .all()
    )
    _city_revenue_total = sum(city_data) or 1
    city_performance = [
        {
            "name": row.city or "Unknown",
            "revenue": float(row.total),
            "customers": city_customer_counts.get(row.city, 0),
            "pct": round(float(row.total) / _city_revenue_total * 100),
            "avg_per_customer": round(
                float(row.total) / city_customer_counts.get(row.city, 1)
                if city_customer_counts.get(row.city) else float(row.total)
            ),
        }
        for row in collections_by_city
    ]

    # --- Customer status distribution (excludes 'deleted' so it doesn't skew the mix) ---
    status_dist = (
        db.session.query(
            Customer.status,
            func.count(Customer.id),
        )
        .filter(Customer.status != "deleted")
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

    efficiency_labels = [f"W{int(row.wk):02d}" for row in weekly_efficiency]
    efficiency_total = [row.total for row in weekly_efficiency]
    efficiency_completed = [int(row.completed) for row in weekly_efficiency]
    efficiency_pct = [
        round(c / t * 100) if t else 0
        for c, t in zip(efficiency_completed, efficiency_total)
    ]

    # --- KPI: Totals for current and previous periods ---
    total_revenue = sum(revenue_data) if revenue_data else 0
    prev_total_revenue = sum(prev_revenue_data) if prev_revenue_data else 0

    # Profit + margin (now that total_revenue exists)
    profit = float(total_revenue) - total_purchases
    prev_profit = float(prev_total_revenue) - prev_total_purchases
    profit_margin = round((profit / float(total_revenue)) * 100, 1) if total_revenue else 0.0

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

    # Matches the balances page policy: count any non-deleted customer with balance > 0.
    total_outstanding, customers_with_balance = db.session.query(
        func.coalesce(func.sum(Customer.balance), 0),
        func.count(Customer.id),
    ).filter(Customer.status != "deleted", Customer.balance > 0).one()
    total_outstanding = float(total_outstanding)

    # --- Top stores by revenue ---
    top_stores_rows = (
        db.session.query(
            Customer.id,
            Customer.name,
            Customer.city,
            func.sum(Payment.amount_sold).label("revenue"),
            func.count(Payment.id).label("payment_count"),
            func.avg(Payment.amount_sold).label("avg_payment"),
        )
        .join(Payment, Payment.customer_id == Customer.id)
        .filter(Payment.payment_date >= range_start)
        .group_by(Customer.id, Customer.name, Customer.city)
        .order_by(func.sum(Payment.amount_sold).desc())
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
    from app.helpers import get_needs_attention
    attention_list = get_needs_attention(limit=10)

    # --- Best collection days (day of week averages) ---
    # Use extract('dow') for Postgres (0=Sun), strftime for SQLite
    try:
        dow_rows = (
            db.session.query(
                extract("isodow", Payment.payment_date).label("dow"),
                func.avg(Payment.amount_sold).label("avg_amount"),
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
        "cashflow": {
            "labels": cashflow_labels,
            "revenue": revenue_aligned,
            "purchases": purchase_aligned,
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
            "pct": efficiency_pct,
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

    # --- Auto-derived insights for the top strip ---
    insights = []

    # Best day of week (highest avg)
    if day_of_week_data:
        best_idx = day_of_week_data.index(max(day_of_week_data))
        insights.append({
            "tone": "emerald",
            "icon": "calendar",
            "label": "Best day",
            "text": f"{day_of_week_labels[best_idx]} averages ${day_of_week_data[best_idx]:,.0f}/sale",
        })

    # Customer concentration (top 5 of top_stores vs all revenue)
    if top_stores and total_revenue:
        top5_revenue = sum(s["revenue"] for s in top_stores[:5])
        concentration_pct = round(top5_revenue / total_revenue * 100)
        insights.append({
            "tone": "indigo",
            "icon": "trending",
            "label": "Top 5 customers",
            "text": f"{concentration_pct}% of revenue (${top5_revenue:,.0f})",
        })

    # Top city
    if city_labels and city_data and total_revenue:
        top_city_revenue = city_data[0]
        top_city_pct = round(top_city_revenue / total_revenue * 100)
        insights.append({
            "tone": "blue",
            "icon": "pin",
            "label": "Top city",
            "text": f"{city_labels[0]} ({top_city_pct}% — ${top_city_revenue:,.0f})",
        })

    # Stale-customer alert
    stale_60 = sum(
        1 for s in attention_list
        if s.get("days_since") is None or s.get("days_since", 0) > 60
    )
    if stale_60 > 0:
        insights.append({
            "tone": "rose",
            "icon": "alert",
            "label": "At risk",
            "text": f"{stale_60} customer{'s' if stale_60 != 1 else ''} not visited in 60+ days",
        })

    # Margin insight (replaces "Top city" if margin is more useful — keep both, ordered)
    if total_revenue and total_purchases:
        margin_tone = (
            "emerald" if profit_margin > 30
            else ("amber" if profit_margin > 15 else "rose")
        )
        # Insert margin near the front so it shows in the top 4
        insights.insert(0, {
            "tone": margin_tone,
            "icon": "trending",
            "label": "Margin",
            "text": f"{profit_margin}% — ${profit:,.0f} profit",
        })

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
        top_suppliers=top_suppliers,
        city_performance=city_performance,
        attention_list=attention_list,
        insights=insights,
        total_purchases=total_purchases,
        prev_total_purchases=prev_total_purchases,
        purchases_delta=pct_change(total_purchases, prev_total_purchases),
        profit=profit,
        prev_profit=prev_profit,
        profit_delta=pct_change(profit, prev_profit),
        profit_margin=profit_margin,
        today=today,
    )
