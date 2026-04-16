"""Planner blueprint – calendar-based route planning."""

from datetime import date, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db
from app.helpers import staff_required
from app.models import Customer, RouteStop, RecurringStop, RecurringSkip

bp = Blueprint("planner", __name__, url_prefix="/planner")


def _auto_populate_recurring(target_date):
    """Create RouteStops from active recurring schedules for target_date."""
    existing_ids = {
        s.customer_id
        for s in RouteStop.query.filter(RouteStop.route_date == target_date).all()
    }

    recurring = RecurringStop.query.filter(
        RecurringStop.is_active.is_(True),
        RecurringStop.start_date <= target_date,
    ).all()

    matching = [r for r in recurring if r.matches(target_date) and r.customer_id not in existing_ids]
    if not matching:
        return

    # Check for skips
    matching_ids = [r.id for r in matching]
    skipped = {
        s.recurring_stop_id
        for s in RecurringSkip.query.filter(
            RecurringSkip.recurring_stop_id.in_(matching_ids),
            RecurringSkip.skip_date == target_date,
        ).all()
    }

    max_seq = (
        db.session.query(db.func.max(RouteStop.sequence))
        .filter(RouteStop.route_date == target_date)
        .scalar()
    ) or 0

    added = 0
    for r in matching:
        if r.id in skipped:
            continue
        max_seq += 1
        db.session.add(RouteStop(
            customer_id=r.customer_id,
            route_date=target_date,
            sequence=max_seq,
            created_by=r.created_by,
        ))
        added += 1

    if added:
        db.session.commit()


@bp.route("/")
@login_required
def index():
    """Route planner with calendar view. Shows stops for selected date."""
    date_param = request.args.get("date", "")
    if date_param:
        try:
            selected_date = date.fromisoformat(date_param)
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    # Auto-populate from recurring schedules
    _auto_populate_recurring(selected_date)

    stops = (
        RouteStop.query
        .options(joinedload(RouteStop.customer))
        .join(Customer)
        .filter(RouteStop.route_date == selected_date)
        .order_by(RouteStop.sequence)
        .all()
    )

    customers = (
        Customer.query
        .filter(Customer.status == "active")
        .order_by(Customer.city, Customer.name)
        .all()
    )

    # Cities with customer counts for the bulk-add panel
    cities = (
        db.session.query(Customer.city, func.count(Customer.id).label("count"))
        .filter(Customer.status == "active", Customer.city.isnot(None), Customer.city != "")
        .group_by(Customer.city)
        .order_by(func.count(Customer.id).desc())
        .all()
    )

    # IDs already on this date's route
    existing_ids = {s.customer_id for s in stops}

    stops_json = [
        {
            "id": s.id,
            "customer_id": s.customer_id,
            "customer_name": s.customer.name,
            "city": s.customer.city or "",
            "sequence": s.sequence,
            "completed": s.completed,
        }
        for s in stops
    ]

    customers_json = [
        {
            "id": c.id,
            "name": c.name,
            "city": c.city or "",
            "phone": c.phone or "",
            "balance": float(c.balance) if c.balance else 0.0,
        }
        for c in customers
    ]

    # Active recurring schedules
    recurring_stops = (
        RecurringStop.query
        .options(joinedload(RecurringStop.customer))
        .join(Customer)
        .filter(RecurringStop.is_active.is_(True))
        .order_by(Customer.name)
        .all()
    )
    recurring_json = [
        {
            "id": r.id,
            "customer_id": r.customer_id,
            "customer_name": r.customer.name,
            "city": r.customer.city or "",
            "interval_days": r.interval_days,
            "frequency_label": r.frequency_label,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat() if r.end_date else None,
        }
        for r in recurring_stops
    ]

    return render_template(
        "planner.html",
        selected_date=selected_date,
        stops=stops,
        stops_json=stops_json,
        customers=customers,
        customers_json=customers_json,
        cities=cities,
        existing_ids=existing_ids,
        recurring_json=recurring_json,
    )


# ---------------------------------------------------------------------------
# Add stop
# ---------------------------------------------------------------------------

@bp.route("/add-stop", methods=["POST"])
@login_required
@staff_required
def add_stop():
    """Add a customer to a route date."""
    customer_id = request.form.get("customer_id", type=int)
    route_date_str = request.form.get("route_date", "")
    sequence = request.form.get("sequence", 0, type=int)

    if not customer_id or not route_date_str:
        flash("Customer and date are required.", "error")
        return redirect(url_for("planner.index"))

    try:
        route_date = date.fromisoformat(route_date_str)
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("planner.index"))

    customer = Customer.query.get_or_404(customer_id)

    # Prevent duplicate stops on the same date
    existing = RouteStop.query.filter_by(customer_id=customer_id, route_date=route_date).first()
    if existing:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": f"{customer.name} is already on this route."}), 409
        flash(f"{customer.name} is already on this route.", "warning")
        return redirect(url_for("planner.index", date=route_date.isoformat()))

    # Auto-sequence if none provided
    if sequence == 0:
        max_seq = (
            db.session.query(db.func.max(RouteStop.sequence))
            .filter(RouteStop.route_date == route_date)
            .scalar()
        ) or 0
        sequence = max_seq + 1

    stop = RouteStop(
        customer_id=customer.id,
        route_date=route_date,
        sequence=sequence,
        created_by=current_user.id,
    )
    db.session.add(stop)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "id": stop.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "city": customer.city or "",
            "sequence": stop.sequence,
            "completed": False,
        })

    flash(f"{customer.name} added to route on {route_date.isoformat()}.", "success")
    return redirect(url_for("planner.index", date=route_date.isoformat()))


# ---------------------------------------------------------------------------
# Add city (bulk)
# ---------------------------------------------------------------------------

@bp.route("/add-city", methods=["POST"])
@login_required
@staff_required
def add_city():
    """Add all active customers in a city to a route date."""
    city = request.form.get("city", "").strip()
    route_date_str = request.form.get("route_date", "")

    if not city or not route_date_str:
        flash("City and date are required.", "error")
        return redirect(url_for("planner.index"))

    try:
        route_date = date.fromisoformat(route_date_str)
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("planner.index"))

    # Get customers in this city not already on the route
    existing_ids = {
        s.customer_id
        for s in RouteStop.query.filter(RouteStop.route_date == route_date).all()
    }

    city_customers = (
        Customer.query
        .filter(Customer.status == "active", Customer.city == city)
        .order_by(Customer.name)
        .all()
    )

    max_seq = (
        db.session.query(db.func.max(RouteStop.sequence))
        .filter(RouteStop.route_date == route_date)
        .scalar()
    ) or 0

    added = 0
    for c in city_customers:
        if c.id not in existing_ids:
            max_seq += 1
            db.session.add(RouteStop(
                customer_id=c.id,
                route_date=route_date,
                sequence=max_seq,
                created_by=current_user.id,
            ))
            added += 1

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Return all stops for this date so the client can rebuild
        all_stops = (
            RouteStop.query.options(joinedload(RouteStop.customer))
            .join(Customer)
            .filter(RouteStop.route_date == route_date)
            .order_by(RouteStop.sequence).all()
        )
        return jsonify({
            "added": added,
            "stops": [
                {"id": s.id, "customer_id": s.customer_id, "customer_name": s.customer.name,
                 "city": s.customer.city or "", "sequence": s.sequence, "completed": s.completed}
                for s in all_stops
            ],
        })

    if added:
        flash(f"Added {added} stop{'s' if added != 1 else ''} from {city}.", "success")
    else:
        flash(f"All customers in {city} are already on this route.", "warning")

    return redirect(url_for("planner.index", date=route_date.isoformat()))


# ---------------------------------------------------------------------------
# Remove stop
# ---------------------------------------------------------------------------

@bp.route("/remove-stop/<int:id>", methods=["POST"])
@login_required
@staff_required
def remove_stop(id):
    """Remove a stop from the route. If it came from a recurring schedule, skip that date."""
    stop = RouteStop.query.get_or_404(id)
    customer_id = stop.customer_id
    route_date = stop.route_date

    # Check if any recurring schedule would regenerate this stop
    recurring = RecurringStop.query.filter(
        RecurringStop.customer_id == customer_id,
        RecurringStop.is_active.is_(True),
    ).all()
    for r in recurring:
        if r.matches(route_date):
            existing_skip = RecurringSkip.query.filter_by(
                recurring_stop_id=r.id, skip_date=route_date
            ).first()
            if not existing_skip:
                db.session.add(RecurringSkip(recurring_stop_id=r.id, skip_date=route_date))

    db.session.delete(stop)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "customer_id": customer_id})

    flash("Stop removed from route.", "success")
    return redirect(url_for("planner.index", date=stop.route_date.isoformat()))


# ---------------------------------------------------------------------------
# Reorder stops
# ---------------------------------------------------------------------------

@bp.route("/reorder", methods=["POST"])
@login_required
@staff_required
def reorder():
    """Receive JSON array of stop IDs in new order and update sequences."""
    data = request.get_json(silent=True)
    if not data or "stop_ids" not in data:
        return jsonify({"error": "Missing stop_ids array."}), 400

    stop_ids = data["stop_ids"]
    if not isinstance(stop_ids, list):
        return jsonify({"error": "stop_ids must be an array."}), 400

    # Validate all stops exist and belong to the same date
    stops = RouteStop.query.filter(RouteStop.id.in_(stop_ids)).all()
    stop_map = {s.id: s for s in stops}
    dates = {s.route_date for s in stops}
    if len(dates) > 1:
        return jsonify({"error": "Cannot reorder stops across different dates."}), 400

    for index, stop_id in enumerate(stop_ids, start=1):
        if stop_id in stop_map:
            stop_map[stop_id].sequence = index

    db.session.commit()
    return jsonify({"success": True, "count": len(stop_ids)})


# ---------------------------------------------------------------------------
# Recurring schedules
# ---------------------------------------------------------------------------

@bp.route("/recurring", methods=["GET"])
@login_required
def recurring_list():
    """Return all active recurring schedules as JSON."""
    recurring = (
        RecurringStop.query
        .join(Customer)
        .filter(RecurringStop.is_active.is_(True))
        .order_by(Customer.name)
        .all()
    )
    return jsonify([
        {
            "id": r.id,
            "customer_id": r.customer_id,
            "customer_name": r.customer.name,
            "city": r.customer.city or "",
            "interval_days": r.interval_days,
            "frequency_label": r.frequency_label,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat() if r.end_date else None,
        }
        for r in recurring
    ])


@bp.route("/recurring/add", methods=["POST"])
@login_required
@staff_required
def recurring_add():
    """Create a recurring schedule for a customer."""
    customer_id = request.form.get("customer_id", type=int)
    interval_days = request.form.get("interval_days", type=int)
    start_date_str = request.form.get("start_date", "")

    if not customer_id or not interval_days or not start_date_str:
        return jsonify({"error": "customer_id, interval_days, and start_date are required."}), 400

    if interval_days < 1 or interval_days > 365:
        return jsonify({"error": "Interval must be between 1 and 365 days."}), 400

    try:
        start = date.fromisoformat(start_date_str)
    except ValueError:
        return jsonify({"error": "Invalid start_date."}), 400

    customer = Customer.query.get_or_404(customer_id)

    # Check for existing active schedule for this customer
    existing = RecurringStop.query.filter_by(
        customer_id=customer_id, is_active=True
    ).first()
    if existing:
        # Update instead of duplicate
        existing.interval_days = interval_days
        existing.start_date = start
        existing.end_date = None
        db.session.commit()
        r = existing
    else:
        r = RecurringStop(
            customer_id=customer_id,
            interval_days=interval_days,
            start_date=start,
            created_by=current_user.id,
        )
        db.session.add(r)
        db.session.commit()

    return jsonify({
        "id": r.id,
        "customer_id": r.customer_id,
        "customer_name": customer.name,
        "city": customer.city or "",
        "interval_days": r.interval_days,
        "frequency_label": r.frequency_label,
        "start_date": r.start_date.isoformat(),
        "end_date": None,
    })


@bp.route("/recurring/<int:id>/delete", methods=["POST"])
@login_required
@staff_required
def recurring_delete(id):
    """Deactivate a recurring schedule."""
    r = RecurringStop.query.get_or_404(id)
    r.is_active = False
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# All stops (JSON for calendar / Alpine.js)
# ---------------------------------------------------------------------------

@bp.route("/all-stops")
@login_required
def all_stops():
    """Return JSON of stop counts per date for calendar rendering."""
    cutoff = date.today() - timedelta(days=90)
    rows = (
        db.session.query(
            RouteStop.route_date,
            func.count(RouteStop.id).label("total"),
            func.sum(db.case((RouteStop.completed.is_(True), 1), else_=0)).label("done"),
        )
        .filter(RouteStop.route_date >= cutoff)
        .group_by(RouteStop.route_date)
        .all()
    )

    result = {}
    for r in rows:
        result[r.route_date.isoformat()] = {
            "total": r.total,
            "done": int(r.done or 0),
        }

    return jsonify(result)
