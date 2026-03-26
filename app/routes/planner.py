"""Planner blueprint – calendar-based route planning."""

from datetime import date

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify,
)
from flask_login import login_required, current_user

from app import db
from app.models import Customer, RouteStop

bp = Blueprint("planner", __name__, url_prefix="/planner")


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

    stops = (
        RouteStop.query
        .join(Customer)
        .filter(RouteStop.route_date == selected_date)
        .order_by(RouteStop.sequence)
        .all()
    )

    customers = (
        Customer.query
        .filter(Customer.status == "active")
        .order_by(Customer.name)
        .all()
    )

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

    return render_template(
        "planner.html",
        selected_date=selected_date,
        stops=stops,
        stops_json=stops_json,
        customers=customers,
    )


# ---------------------------------------------------------------------------
# Add stop
# ---------------------------------------------------------------------------

@bp.route("/add-stop", methods=["POST"])
@login_required
def add_stop():
    """Add a customer to a route date."""
    customer_id = request.form.get("customer_id", type=int)
    route_date_str = request.form.get("route_date", "")
    sequence = request.form.get("sequence", 0, type=int)

    if not customer_id or not route_date_str:
        flash("Customer and date are required.", "danger")
        return redirect(url_for("planner.index"))

    try:
        route_date = date.fromisoformat(route_date_str)
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("planner.index"))

    customer = Customer.query.get_or_404(customer_id)

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

    flash(f"{customer.name} added to route on {route_date.isoformat()}.", "success")
    return redirect(url_for("planner.index", date=route_date.isoformat()))


# ---------------------------------------------------------------------------
# Remove stop
# ---------------------------------------------------------------------------

@bp.route("/remove-stop/<int:id>", methods=["POST"])
@login_required
def remove_stop(id):
    """Remove a stop from the route."""
    stop = RouteStop.query.get_or_404(id)
    route_date = stop.route_date
    db.session.delete(stop)
    db.session.commit()

    flash("Stop removed from route.", "success")
    return redirect(url_for("planner.index", date=route_date.isoformat()))


# ---------------------------------------------------------------------------
# Reorder stops
# ---------------------------------------------------------------------------

@bp.route("/reorder", methods=["POST"])
@login_required
def reorder():
    """Receive JSON array of stop IDs in new order and update sequences."""
    data = request.get_json(silent=True)
    if not data or "stop_ids" not in data:
        return jsonify({"error": "Missing stop_ids array."}), 400

    stop_ids = data["stop_ids"]
    if not isinstance(stop_ids, list):
        return jsonify({"error": "stop_ids must be an array."}), 400

    for index, stop_id in enumerate(stop_ids, start=1):
        stop = RouteStop.query.get(stop_id)
        if stop:
            stop.sequence = index

    db.session.commit()
    return jsonify({"success": True, "count": len(stop_ids)})


# ---------------------------------------------------------------------------
# All stops (JSON for calendar / Alpine.js)
# ---------------------------------------------------------------------------

@bp.route("/all-stops")
@login_required
def all_stops():
    """Return JSON of all stops, grouped by date, for calendar rendering."""
    stops = (
        RouteStop.query
        .join(Customer)
        .order_by(RouteStop.route_date, RouteStop.sequence)
        .all()
    )

    result = {}
    for stop in stops:
        key = stop.route_date.isoformat()
        if key not in result:
            result[key] = []
        result[key].append({
            "id": stop.id,
            "customer_id": stop.customer_id,
            "customer_name": stop.customer.name,
            "city": stop.customer.city,
            "sequence": stop.sequence,
            "completed": stop.completed,
        })

    return jsonify(result)
