from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .store import (
    add_customer_to_route,
    complete_stop,
    get_today_route_stops,
    remove_stop,
    update_stop_notes,
)

route_bp = Blueprint("route", __name__)


@route_bp.route("/route")
def route():
    stops = get_today_route_stops()
    today = datetime.now()
    return render_template("route.html", stops=stops, today=today)


@route_bp.post("/route/add")
def route_add():
    """Add a customer to a route (supports optional date, defaults to today)"""
    customer_id = request.form.get("customer_id")
    date_str = request.form.get("date")

    if not customer_id:
        flash("No customer selected", "error")
        return redirect(url_for("route.route"))

    try:
        target_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        target_date = date.today()

    add_customer_to_route(target_date, int(customer_id))
    flash("Customer added to route", "success")

    return redirect(url_for("route.route"))


@route_bp.post("/route/complete/<int:stop_id>")
def route_complete(stop_id: int):
    complete_stop(stop_id)
    return redirect(url_for("route.route"))


@route_bp.post("/route/remove/<int:stop_id>")
def route_remove(stop_id: int):
    remove_stop(stop_id)
    return redirect(url_for("route.route"))


@route_bp.post("/route/<int:stop_id>/notes")
def route_update_notes(stop_id: int):
    """Update notes for a specific route stop"""
    notes = request.form.get("notes", "")
    update_stop_notes(stop_id, notes)
    return redirect(url_for("route.route"))
