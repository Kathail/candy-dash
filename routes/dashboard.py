# routes/dashboard.py
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template

from .db import get_conn

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
def dashboard():
    """Main dashboard with comprehensive stats"""
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    now = datetime.now(timezone.utc)  # Make timezone-aware

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Total customers
            cur.execute("SELECT COUNT(*) as total FROM customers")
            total_customers = cur.fetchone()["total"]

            # Total owed and number of customers owing
            cur.execute("""
                SELECT
                    COALESCE(SUM(balance_cents), 0) as total_owed,
                    COUNT(*) FILTER (WHERE balance_cents > 0) as customers_owing
                FROM customers
            """)
            owed_stats = cur.fetchone()
            total_owed_cents = owed_stats["total_owed"]
            customers_owing = owed_stats["customers_owing"]

            # Today's route progress
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_stops,
                    COUNT(*) FILTER (WHERE completed = true) as completed_today
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                WHERE r.route_date = %s
            """,
                (today,),
            )
            route_stats = cur.fetchone()
            total_stops_today = route_stats["total_stops"]
            completed_today = route_stats["completed_today"]

            # Collected today
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(amount_cents), 0) as collected,
                    COUNT(*) as payment_count
                FROM payments
                WHERE DATE(received_at) = %s
            """,
                (today,),
            )
            payment_stats = cur.fetchone()
            collected_today_cents = payment_stats["collected"]
            payments_today = payment_stats["payment_count"]

            # Weekly stats
            cur.execute(
                """
                SELECT COUNT(*) as weekly_stops
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                WHERE r.route_date >= %s
                AND rs.completed = true
            """,
                (week_ago,),
            )
            weekly_stops = cur.fetchone()["weekly_stops"]

            cur.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) as weekly_collected
                FROM payments
                WHERE received_at >= %s
            """,
                (week_ago,),
            )
            weekly_collected_cents = cur.fetchone()["weekly_collected"]

            # New customers this week
            cur.execute(
                """
                SELECT COUNT(*) as new_customers
                FROM customers
                WHERE created_at >= %s
            """,
                (week_ago,),
            )
            new_customers_week = cur.fetchone()["new_customers"]

            # Recent activity (last 24 hours)
            recent_activity = []

            # Completed visits
            cur.execute("""
                SELECT
                    c.name as customer_name,
                    rs.completed_at
                FROM route_stops rs
                JOIN customers c ON rs.customer_id = c.id
                WHERE rs.completed = true
                AND rs.completed_at >= NOW() - INTERVAL '24 hours'
                ORDER BY rs.completed_at DESC
                LIMIT 10
            """)
            for row in cur.fetchall():
                # Make sure completed_at is timezone-aware
                completed_at = row["completed_at"]
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)

                time_diff = now - completed_at
                hours_ago = int(time_diff.total_seconds() / 3600)
                recent_activity.append(
                    {
                        "type": "completed",
                        "customer_name": row["customer_name"],
                        "time_ago": f"{hours_ago}h ago"
                        if hours_ago > 0
                        else "Just now",
                        "timestamp": completed_at,
                    }
                )

            # Recent payments
            cur.execute("""
                SELECT
                    c.name as customer_name,
                    p.received_at,
                    p.amount_cents
                FROM payments p
                JOIN customers c ON p.customer_id = c.id
                WHERE p.received_at >= NOW() - INTERVAL '24 hours'
                ORDER BY p.received_at DESC
                LIMIT 10
            """)
            for row in cur.fetchall():
                # Make sure received_at is timezone-aware
                received_at = row["received_at"]
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)

                time_diff = now - received_at
                hours_ago = int(time_diff.total_seconds() / 3600)
                recent_activity.append(
                    {
                        "type": "payment",
                        "customer_name": row["customer_name"],
                        "amount": f"{row['amount_cents'] / 100:.2f}",
                        "time_ago": f"{hours_ago}h ago"
                        if hours_ago > 0
                        else "Just now",
                        "timestamp": received_at,
                    }
                )

            # Sort all activity by timestamp
            recent_activity = sorted(
                recent_activity, key=lambda x: x["timestamp"], reverse=True
            )[:10]

    return render_template(
        "dashboard.html",
        now=now,
        total_customers=total_customers,
        total_owed_cents=total_owed_cents,
        customers_owing=customers_owing,
        completed_today=completed_today,
        total_stops_today=total_stops_today,
        collected_today_cents=collected_today_cents,
        payments_today=payments_today,
        weekly_stops=weekly_stops,
        weekly_collected_cents=weekly_collected_cents,
        new_customers_week=new_customers_week,
        recent_activity=recent_activity,
    )
