@calendar_bp.route("/")
def calendar():
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # These are not used in current template → optional to keep or remove
            # priority_visits = fetch_priority_customers(cur)
            # visits_this_week, visits_this_month, avg_per_week, completion_rate = fetch_visit_analytics(cur, today)
            # all_customers = ... (not used)

            scheduled_visits = fetch_scheduled_routes(cur, today)

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
        # Remove if not used in template:
        # priority_visits=priority_visits,
        # visits_this_week=visits_this_week,
        # visits_this_month=visits_this_month,
        # avg_per_week=round(avg_per_week, 1),
        # completion_rate=round(completion_rate, 1),
        # all_customers=all_customers,
    )
