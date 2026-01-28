@calendar_bp.route("/")
def calendar():
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Priority / urgent customers (for Priority Visits card)
            priority_visits = fetch_priority_customers(cur)

            # 2. Analytics numbers (for Visit Analytics cards)
            visits_this_week, visits_this_month, avg_per_week, completion_rate = (
                fetch_visit_analytics(cur, today)
            )

            # 3. Count never visited customers (for New Customers badge)
            cur.execute(
                """
                SELECT last_visit_at
                FROM customers
                """
            )
            never_visited = sum(
                1 for row in cur.fetchall() if row["last_visit_at"] is None
            )

            # 4. Scheduled visits + date ranges for calendar display
            scheduled_visits = fetch_scheduled_routes(cur, today)

            # Week: Monday → Sunday
            week_start = today - timedelta(days=today.weekday())
            week_dates = [
                (week_start + timedelta(days=i)).isoformat() for i in range(7)
            ]

            # Full current month
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
        # ── All variables the enhanced template expects ──
        priority_visits=priority_visits,
        visits_this_week=visits_this_week,
        visits_this_month=visits_this_month,
        avg_per_week=round(avg_per_week, 1),
        completion_rate=round(completion_rate, 1),
        never_visited=never_visited,
    )
