@calendar_bp.route("/")
def calendar():
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Priority / urgent customers (used in Priority Visits card)
            priority_visits = fetch_priority_customers(cur)

            # Analytics numbers (used in Visit Analytics cards)
            visits_this_week, visits_this_month, avg_per_week, completion_rate = (
                fetch_visit_analytics(cur, today)
            )

            # All customers — needed to count never-visited for the badge
            cur.execute(
                """
                SELECT id, name, last_visit_at
                FROM customers
                ORDER BY name
                """
            )
            all_customers = cur.fetchall()

            # Count how many customers have never been visited
            never_visited = sum(1 for c in all_customers if c["last_visit_at"] is None)

            # Scheduled visits + date ranges for calendar display
            scheduled_visits = fetch_scheduled_routes(cur, today)

            # Week range (Monday to Sunday)
            week_start = today - timedelta(days=today.weekday())  # Monday
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
        # Variables needed for the enhanced cards and badges
        priority_visits=priority_visits,
        visits_this_week=visits_this_week,
        visits_this_month=visits_this_month,
        avg_per_week=round(avg_per_week, 1),
        completion_rate=round(completion_rate, 1),
        never_visited=never_visited,
        # Optional — can be removed if not used in template
        # all_customers=all_customers,
    )
