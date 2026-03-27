"""JSON API routes for search, offline caching, and sync."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.helpers import generate_receipt_number, audit
from app.models import Customer, Payment, RouteStop, ActivityLog

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
@login_required
def before_request():
    """Require login for all API routes."""
    pass


@bp.route("/customers/search")
def customer_search():
    """Search customers by name, returning JSON results."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    customers = (
        Customer.query
        .filter(Customer.name.ilike(f"%{q}%"))
        .order_by(Customer.name)
        .limit(20)
        .all()
    )

    results = [
        {
            "id": c.id,
            "name": c.name,
            "city": c.city,
            "balance": float(c.balance) if c.balance else 0.0,
            "phone": c.phone,
        }
        for c in customers
    ]
    return jsonify(results)


@bp.route("/route/today")
def route_today():
    """Full route data for today as JSON, suitable for offline caching."""
    today = date.today()

    stops = (
        RouteStop.query
        .filter(RouteStop.route_date == today)
        .order_by(RouteStop.sequence)
        .all()
    )

    data = []
    for stop in stops:
        customer = stop.customer
        data.append({
            "stop_id": stop.id,
            "sequence": stop.sequence,
            "completed": stop.completed,
            "completed_at": stop.completed_at.isoformat() if stop.completed_at else None,
            "notes": stop.notes,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "address": customer.address,
                "city": customer.city,
                "phone": customer.phone,
                "balance": float(customer.balance) if customer.balance else 0.0,
            },
        })

    return jsonify({
        "route_date": today.isoformat(),
        "total_stops": len(data),
        "stops": data,
    })


@bp.route("/sync", methods=["POST"])
def sync():
    """Process offline payment queue.

    Expects a JSON array of payment objects:
        [{"customer_id": 1, "amount": "50.00", "notes": "...", "offline_id": "abc"}, ...]

    Returns results with current balances.
    """
    raw = request.get_json(silent=True)
    if not raw:
        return jsonify({"error": "Expected JSON payload."}), 400

    # Accept either a raw array or {"payments": [...]}
    if isinstance(raw, list):
        payments_data = raw
    elif isinstance(raw, dict) and "payments" in raw:
        payments_data = raw["payments"]
    else:
        return jsonify({"error": "Expected a JSON array of payments."}), 400

    if not isinstance(payments_data, list):
        return jsonify({"error": "Expected a JSON array of payments."}), 400

    results = []

    for entry in payments_data:
        offline_id = entry.get("offline_id", "")
        customer_id = entry.get("customer_id")
        result = {"offline_id": offline_id, "customer_id": customer_id}

        if not customer_id:
            result["status"] = "error"
            result["message"] = "Missing customer_id."
            results.append(result)
            continue

        try:
            amount = Decimal(str(entry.get("amount", "0")))
        except (InvalidOperation, TypeError, ValueError):
            result["status"] = "error"
            result["message"] = "Invalid amount."
            results.append(result)
            continue

        if amount <= 0:
            result["status"] = "error"
            result["message"] = "Amount must be greater than zero."
            results.append(result)
            continue

        try:
            customer = db.session.query(Customer).filter_by(id=customer_id).with_for_update().first()
            if customer is None:
                result["status"] = "error"
                result["message"] = "Customer not found."
                results.append(result)
                continue

            previous_balance = customer.balance
            receipt_number = generate_receipt_number()
            notes = entry.get("notes", "")

            payment = Payment(
                customer_id=customer.id,
                amount=amount,
                receipt_number=receipt_number,
                previous_balance=previous_balance,
                notes=notes,
                recorded_by=current_user.id,
            )
            customer.balance = previous_balance - amount

            log = ActivityLog(
                customer_id=customer.id,
                user_id=current_user.id,
                action="payment",
                description=f"Synced offline payment of ${amount:,.2f}. Receipt: {receipt_number}",
            )

            db.session.add(payment)
            db.session.add(log)
            audit("offline_sync", f"Synced offline payment ${amount:,.2f} for customer #{customer_id} '{customer.name}'. Receipt #{receipt_number}")
            db.session.commit()

            result["status"] = "ok"
            result["receipt_number"] = receipt_number
            result["previous_balance"] = float(previous_balance)
            result["new_balance"] = float(customer.balance)

        except Exception:
            db.session.rollback()
            result["status"] = "error"
            result["message"] = "An internal error occurred while processing this payment."

        results.append(result)

    return jsonify({"results": results})
