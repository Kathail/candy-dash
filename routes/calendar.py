# routes/calendar.py

from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template

from .db import get_conn

# ─────────────────────────────────────────────
# Blueprint MUST be created BEFORE any routes use it
# ─────────────────────────────────────────────
calendar_bp = Blueprint("calendar", __name__)


# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────


def fetch_priority_customers(cur):
    cur.execute(
        """
        SELECT
            c.id,
            c.name,
            c.balance_cents,
            c.last_visit_at,
            COALESCE(DATE_PART('day', NOW() - c.last_visit_at), 999) AS days_since_visit
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
        """
    )
    return cur.fetchall()


def fetch_visit_analytics(cur, today):
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    cur.execute("SELECT COUNT(*) FROM visits WHERE visited_at >= %s", (week_ago,))
    visits_this_week = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM visits WHERE visited_at >= %s", (month_ago,))
    visits_this_month = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COALESCE(COUNT(*)::float / 4, 0)
        FROM visits
        WHERE visited_at >= %s
        """,
        (today - timedelta(days=28),),
    )
    avg_per_week = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COALESCE(
            COUNT(*) FILTER (WHERE rs.completed = true)::float / NULLIF(COUNT(*), 0) * 100,
            0
        )
        FROM route_stops rs
        JOIN routes r ON rs.route_id = r.id
        WHERE r.route_date >= %s
        """,
        (month_ago,),
    )
    completion_rate = cur.fetchone()[0]

    return visits_this_week, visits_this_month, avg_per_week, completion_rate


def fetch_scheduled_routes(cur, today):
    cur.execute(
        """
        SELECT
            r.route_date,
            COALESCE(json_agg(
                json_build_object(
                    'customer_name', c.name,
                    'completed', rs.completed
                ) ORDER BY rs.stop_order
            ), '[]'::json) AS visits
        FROM routes r
        JOIN route_stops rs ON r.id = rs.route_id
        JOIN customers c ON rs.customer_id = c.id
        WHERE r.route_date BETWEEN %s AND %s
        GROUP BY r.route_date
        """,
        (today - timedelta(days=7), today + timedelta(days=60)),
    )

    scheduled = {}
    for row in cur.fetchall():
        scheduled[row["route_date"].isoformat()] = row["visits"]

    return scheduled


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────


@calendar_bp.route("/")
def calendar():
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Priority customers for the card
            priority_visits = fetch_priority_customers(cur)

            # Analytics numbers
            visits_this_week, visits_this_month, avg_per_week, completion_rate = (
                fetch_visit_analytics(cur, today)
            )

            # Count never-visited customers (for badge)
            cur.execute("SELECT last_visit_at FROM customers")
            never_visited = sum(
                1 for row in cur.fetchall() if row["last_visit_at"] is None
            )

            # Main calendar data
            scheduled_visits = fetch_scheduled_routes(cur, today)

            # Date ranges
            week_start = today - timedelta(days=today.weekday())  # Monday
            week_dates = [
                (week_start + timedelta(days=i)).isoformat() for i in range(7)
            ]

            month_start = today.replace(day=1)
            month_dates = []
            current = month_start
            while current.month == month_start.month:
                month_dates.append(current.isoformat())
                current += timedelta(days=1)

    return render_template(
        "calendar.html",
        today=today,
        week_dates=week_dates,
        month_dates=month_dates,
        scheduled_visits=scheduled_visits,
        priority_visits=priority_visits,
        visits_this_week=visits_this_week,
        visits_this_month=visits_this_month,
        avg_per_week=round(avg_per_week, 1),
        completion_rate=round(completion_rate, 1),
        never_visited=never_visited,
    )


@calendar_bp.get("/new_customers")
def new_customers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, phone, address, balance_cents, created_at
                FROM customers
                WHERE last_visit_at IS NULL
                ORDER BY created_at DESC
                """
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
                "created_at": c["created_at"].isoformat(),
            }
            for c in customers
        ]
    )


@calendar_bp.get("/overdue")
def overdue_customers():
    cutoff = date.today() - timedelta(days=14)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, name, phone, address, balance_cents, last_visit_at,
                    DATE_PART('day', NOW() - last_visit_at) AS days_since
                FROM customers
                WHERE last_visit_at < %s OR last_visit_at IS NULL
                ORDER BY last_visit_at ASC NULLS FIRST
                """,
                (cutoff,),
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


@calendar_bp.get("/customers_by_area")
def customers_by_area():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, name, address, city, zip_code, balance_cents,
                    COALESCE(DATE_PART('day', NOW() - last_visit_at), 999) AS days_since
                FROM customers
                WHERE
                    balance_cents > 0
                    OR last_visit_at IS NULL
                    OR DATE_PART('day', NOW() - last_visit_at) > 14
                ORDER BY city, zip_code, name
                """
            )
            rows = cur.fetchall()

    grouped = defaultdict(list)
    for r in rows:
        area = r["city"] or r["zip_code"] or "Unknown"
        grouped[area].append(
            {
                "id": r["id"],
                "name": r["name"],
                "address": r["address"] or "No address",
                "balance_cents": r["balance_cents"],
                "days_since": int(r["days_since"]) if r["days_since"] else None,
            }
        )

    return jsonify(dict(sorted(grouped.items(), key=lambda x: (-len(x[1]), x[0]))))
