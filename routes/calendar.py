# routes/calendar.py
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from .db import get_conn

calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.route("/calendar")
def calendar():
    """Calendar view with visit planning"""
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get priority visits (customers with high balances or not visited recently)
            cur.execute("""
                SELECT
                    c.id,
                    c.name,
                    c.balance_cents,
                    c.last_visit_at,
                    COALESCE(DATE_PART('day', NOW() - c.last_visit_at), 999) as days_since_visit
                FROM customers c
                WHERE c.balance_cents > 0 OR c.last_visit_at IS NULL
                ORDER BY
                    CASE
                        WHEN c.last_visit_at IS NULL THEN 0
                        WHEN c.balance_cents > 10000 THEN 1
                        ELSE 2
                    END,
                    c.last_visit_at ASC NULLS FIRST
                LIMIT 10
            """)
            priority_visits = cur.fetchall()

            # Visit analytics
            week_ago = today - timedelta(days=7)
            month_ago = today - timedelta(days=30)

            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM visits
                WHERE visited_at >= %s
            """,
                (week_ago,),
            )
            visits_this_week = cur.fetchone()["count"]

            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM visits
                WHERE visited_at >= %s
            """,
                (month_ago,),
            )
            visits_this_month = cur.fetchone()["count"]

            # Average visits per week (last 4 weeks)
            cur.execute(
                """
                SELECT COUNT(*)::float / 4 as avg_per_week
                FROM visits
                WHERE visited_at >= %s
            """,
                (today - timedelta(days=28),),
            )
            avg_per_week = cur.fetchone()["avg_per_week"] or 0

            # Completion rate (completed vs total stops this month)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE completed = true)::float / NULLIF(COUNT(*), 0) * 100 as rate
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                WHERE r.route_date >= %s
            """,
                (month_ago,),
            )
            completion_rate = cur.fetchone()["rate"] or 0

            # Get all customers for the quick add modal
            cur.execute("""
                SELECT id, name, balance_cents, last_visit_at
                FROM customers
                ORDER BY name
            """)
            all_customers = cur.fetchall()

            # Get scheduled visits (planned routes) - convert dates to strings for JSON
            cur.execute(
                """
                SELECT
                    r.route_date,
                    json_agg(
                        json_build_object(
                            'customer_id', c.id,
                            'customer_name', c.name,
                            'balance_cents', c.balance_cents,
                            'completed', rs.completed
                        ) ORDER BY rs.stop_order
                    ) as visits
                FROM routes r
                JOIN route_stops rs ON r.id = rs.route_id
                JOIN customers c ON rs.customer_id = c.id
                WHERE r.route_date >= %s
                AND r.route_date <= %s
                GROUP BY r.route_date
            """,
                (today - timedelta(days=7), today + timedelta(days=60)),
            )

            # Convert date keys to strings for JSON serialization
            scheduled_visits = {}
            for row in cur.fetchall():
                date_str = row["route_date"].isoformat()
                scheduled_visits[date_str] = row["visits"]

    return render_template(
        "calendar.html",
        priority_visits=priority_visits,
        visits_this_week=visits_this_week,
        visits_this_month=visits_this_month,
        avg_per_week=round(avg_per_week, 1),
        completion_rate=round(completion_rate),
        all_customers=all_customers,
        scheduled_visits=scheduled_visits,
        today=today,
    )


@calendar_bp.route("/api/calendar/visits/<date_str>")
def get_visits_for_date(date_str):
    """API endpoint to get visits for a specific date"""
    try:
        visit_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    c.address,
                    c.balance_cents,
                    c.last_visit_at,
                    rs.completed,
                    rs.notes
                FROM routes r
                JOIN route_stops rs ON r.id = rs.route_id
                JOIN customers c ON rs.customer_id = c.id
                WHERE r.route_date = %s
                ORDER BY rs.stop_order
            """,
                (visit_date,),
            )
            visits = cur.fetchall()

            return jsonify(
                [
                    {
                        "id": v["id"],
                        "name": v["name"],
                        "address": v["address"],
                        "balance_cents": v["balance_cents"],
                        "last_visit_at": v["last_visit_at"].isoformat()
                        if v["last_visit_at"]
                        else None,
                        "completed": v["completed"],
                        "notes": v["notes"],
                    }
                    for v in visits
                ]
            )


@calendar_bp.post("/calendar/add_visit")
def add_visit():
    """Add a visit to a specific date"""
    customer_id = request.form.get("customer_id")
    visit_date_str = request.form.get("date")
    notes = request.form.get("notes", "").strip()

    if not customer_id or not visit_date_str:
        flash("Customer and date are required", "error")
        return redirect(url_for("calendar.calendar"))

    try:
        visit_date = datetime.strptime(visit_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date format", "error")
        return redirect(url_for("calendar.calendar"))

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get or create route for that date
            cur.execute(
                """
                INSERT INTO routes (route_date)
                VALUES (%s)
                ON CONFLICT (route_date) DO UPDATE
                SET route_date = %s
                RETURNING id
            """,
                (visit_date, visit_date),
            )
            route_id = cur.fetchone()["id"]

            # Check if customer already on that route
            cur.execute(
                """
                SELECT id FROM route_stops
                WHERE route_id = %s AND customer_id = %s
            """,
                (route_id, customer_id),
            )

            if cur.fetchone():
                flash("Customer is already scheduled for that day", "warning")
                return redirect(url_for("calendar.calendar"))

            # Get next stop order
            cur.execute(
                """
                SELECT COALESCE(MAX(stop_order), -1) + 1 as next_order
                FROM route_stops
                WHERE route_id = %s
            """,
                (route_id,),
            )
            next_order = cur.fetchone()["next_order"]

            # Add the stop
            cur.execute(
                """
                INSERT INTO route_stops (route_id, customer_id, stop_order, notes)
                VALUES (%s, %s, %s, %s)
            """,
                (route_id, customer_id, next_order, notes or None),
            )

            conn.commit()

    flash("Visit scheduled successfully", "success")
    return redirect(url_for("calendar.calendar"))


@calendar_bp.get("/calendar/new_customers")
def new_customers():
    """Get customers who have never been visited"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, phone, address, balance_cents, created_at
                FROM customers
                WHERE last_visit_at IS NULL
                ORDER BY created_at DESC
            """)
            customers = cur.fetchall()

    return jsonify(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "phone": c["phone"],
                "address": c["address"],
                "balance_cents": c["balance_cents"],
                "created_at": c["created_at"].isoformat(),
            }
            for c in customers
        ]
    )


@calendar_bp.get("/calendar/overdue")
def overdue_customers():
    """Get customers not visited in 14+ days"""
    cutoff_date = date.today() - timedelta(days=14)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    phone,
                    address,
                    balance_cents,
                    last_visit_at,
                    DATE_PART('day', NOW() - last_visit_at) as days_since
                FROM customers
                WHERE last_visit_at < %s OR last_visit_at IS NULL
                ORDER BY last_visit_at ASC NULLS FIRST
            """,
                (cutoff_date,),
            )
            customers = cur.fetchall()

    return jsonify(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "phone": c["phone"],
                "address": c["address"],
                "balance_cents": c["balance_cents"],
                "last_visit_at": c["last_visit_at"].isoformat()
                if c["last_visit_at"]
                else None,
                "days_since": int(c["days_since"]) if c["days_since"] else None,
            }
            for c in customers
        ]
    )
