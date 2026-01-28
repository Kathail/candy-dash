# routes/calendar.py

import logging
from collections import defaultdict
from datetime import date, timedelta
from textwrap import dedent

from flask import Blueprint, abort, jsonify, render_template

from .db import get_conn

# Constants for magic numbers
PRIORITY_CUSTOMERS_LIMIT = 10
OVERDUE_DAYS_CUTOFF = 14
ANALYTICS_WEEK_DAYS = 7
ANALYTICS_MONTH_DAYS = 30
ANALYTICS_AVG_WEEK_DAYS = 28
HIGH_BALANCE_THRESHOLD_CENTS = 10000
DAYS_SENTINEL = 999

# Blueprint first — must be before any @calendar_bp decorators
calendar_bp = Blueprint("calendar", __name__)

# Configure logging (assume app-wide config, but basic here if needed)
logging.basicConfig(level=logging.ERROR)

# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────


def fetch_priority_customers(cur):
    """
    Fetch top priority customers based on balance and last visit.
    """
    sql = dedent(
        """
        SELECT
            c.id,
            c.name,
            c.balance_cents,
            c.last_visit_at,
            COALESCE(DATE_PART('day', CURRENT_DATE - c.last_visit_at::date), %s) AS days_since_visit
        FROM customers c
        WHERE c.balance_cents > 0 OR c.last_visit_at IS NULL
        ORDER BY
            CASE
                WHEN c.last_visit_at IS NULL THEN 0
                WHEN c.balance_cents > %s THEN 1
                ELSE 2
            END,
            c.last_visit_at ASC NULLS FIRST
        LIMIT %s
        """
    )
    cur.execute(
        sql, (DAYS_SENTINEL, HIGH_BALANCE_THRESHOLD_CENTS, PRIORITY_CUSTOMERS_LIMIT)
    )
    return cur.fetchall()


def fetch_visit_analytics(cur, today):
    """
    Fetch visit analytics in a single combined query for efficiency.
    """
    week_ago = today - timedelta(days=ANALYTICS_WEEK_DAYS)
    month_ago = today - timedelta(days=ANALYTICS_MONTH_DAYS)
    four_weeks_ago = today - timedelta(days=ANALYTICS_AVG_WEEK_DAYS)

    sql = dedent(
        """
        WITH dates AS (
            SELECT
                %s::date AS week_ago,
                %s::date AS month_ago,
                %s::date AS four_weeks_ago
        ),
        visits_counts AS (
            SELECT
                (SELECT COUNT(*) FROM visits WHERE visited_at >= d.week_ago) AS visits_this_week,
                (SELECT COUNT(*) FROM visits WHERE visited_at >= d.month_ago) AS visits_this_month,
                COALESCE((SELECT COUNT(*)::float / 4 FROM visits WHERE visited_at >= d.four_weeks_ago), 0) AS avg_per_week,
                (SELECT COUNT(*) FROM customers WHERE last_visit_at IS NULL) AS never_visited
            FROM dates d
        ),
        completion AS (
            SELECT COALESCE(
                COUNT(*) FILTER (WHERE rs.completed = true)::float / NULLIF(COUNT(*), 0) * 100,
                0
            ) AS rate
            FROM route_stops rs
            JOIN routes r ON rs.route_id = r.id
            WHERE r.route_date >= (SELECT month_ago FROM dates)
        )
        SELECT
            vc.visits_this_week,
            vc.visits_this_month,
            vc.avg_per_week,
            vc.never_visited,
            c.rate AS completion_rate
        FROM visits_counts vc, completion c
        """
    )
    cur.execute(sql, (week_ago, month_ago, four_weeks_ago))
    row = cur.fetchone()
    return (
        row["visits_this_week"],
        row["visits_this_month"],
        row["avg_per_week"],
        row["completion_rate"],
        row["never_visited"],
    )


def fetch_scheduled_routes(cur, today):
    """
    Fetch scheduled routes with visits aggregated as JSON.
    """
    start_date = today - timedelta(days=ANALYTICS_WEEK_DAYS)
    end_date = today + timedelta(days=60)

    sql = dedent(
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
        """
    )
    cur.execute(sql, (start_date, end_date))

    scheduled = {}
    for row in cur.fetchall():
        date_str = row["route_date"].isoformat()
        scheduled[date_str] = row["visits"]

    return scheduled


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────


@calendar_bp.route("/")
def calendar():
    today = date.today()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                priority_visits = fetch_priority_customers(cur)
                (
                    visits_this_week,
                    visits_this_month,
                    avg_per_week,
                    completion_rate,
                    never_visited,
                ) = fetch_visit_analytics(cur, today)
                scheduled_visits = fetch_scheduled_routes(cur, today)

                week_start = today - timedelta(days=today.weekday())
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
    except Exception as e:
        logging.error(f"Error in calendar route: {str(e)}")
        abort(500, description="Internal server error")


@calendar_bp.get("/new_customers")
def new_customers():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = dedent(
                    """
                    SELECT id, name, phone, address, balance_cents, created_at
                    FROM customers
                    WHERE last_visit_at IS NULL
                    ORDER BY created_at DESC
                    """
                )
                cur.execute(sql)
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
    except Exception as e:
        logging.error(f"Error in new_customers route: {str(e)}")
        abort(500, description="Internal server error")


@calendar_bp.get("/overdue")
def overdue_customers():
    cutoff = date.today() - timedelta(days=OVERDUE_DAYS_CUTOFF)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = dedent(
                    """
                    SELECT
                        id, name, phone, address, balance_cents, last_visit_at,
                        DATE_PART('day', CURRENT_DATE - last_visit_at::date) AS days_since
                    FROM customers
                    WHERE last_visit_at < %s OR last_visit_at IS NULL
                    ORDER BY last_visit_at ASC NULLS FIRST
                    """
                )
                cur.execute(sql, (cutoff,))
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
    except Exception as e:
        logging.error(f"Error in overdue_customers route: {str(e)}")
        abort(500, description="Internal server error")


@calendar_bp.get("/customers_by_area")
def customers_by_area():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = dedent(
                    """
                    SELECT
                        id, name, address, city, zip_code, balance_cents,
                        COALESCE(DATE_PART('day', CURRENT_DATE - last_visit_at::date), %s) AS days_since
                    FROM customers
                    WHERE
                        balance_cents > 0
                        OR last_visit_at IS NULL
                        OR DATE_PART('day', CURRENT_DATE - last_visit_at::date) > %s
                    ORDER BY city, zip_code, name
                    """
                )
                cur.execute(sql, (DAYS_SENTINEL, OVERDUE_DAYS_CUTOFF))
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
    except Exception as e:
        logging.error(f"Error in customers_by_area route: {str(e)}")
        abort(500, description="Internal server error")
