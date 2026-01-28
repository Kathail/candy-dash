# routes/route.py
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for

from .store import (
    add_customer_to_today_route,
    complete_stop,
    get_customer,
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
    """Add a customer to today's route from the search modal"""
    customer_id = request.form.get("customer_id")
    if customer_id:
        add_customer_to_today_route(int(customer_id))
    return redirect(url_for("route.route"))


@route_bp.post("/route/complete/<int:stop_id>")
def route_complete(stop_id):
    complete_stop(stop_id)
    return redirect(url_for("route.route"))


@route_bp.post("/route/remove/<int:stop_id>")
def route_remove(stop_id):
    remove_stop(stop_id)
    return redirect(url_for("route.route"))


@route_bp.post("/route/<int:stop_id>/notes")
def route_update_notes(stop_id):
    """Update notes for a specific stop"""
    notes = request.form.get("notes", "")
    update_stop_notes(stop_id, notes)
    return redirect(url_for("route.route"))
