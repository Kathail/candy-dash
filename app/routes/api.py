"""JSON API routes for search and route data."""

from datetime import date

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app import db
from app.helpers import staff_required
from app.models import Customer, RouteStop

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
@login_required
@staff_required
def before_request():
    """Require login and non-demo role for all API routes."""
    pass


@bp.route("/customers/search")
def customer_search():
    """Search customers by name and payments by receipt number."""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])

    results = []

    # Search receipts if query looks like a receipt number
    if q.upper().startswith("RCP") or q.isdigit():
        from sqlalchemy.orm import joinedload
        from app.helpers import format_date
        from app.models import Payment
        payments = (
            Payment.query
            .options(joinedload(Payment.customer))
            .filter(Payment.receipt_number.ilike(f"%{q}%"))
            .order_by(Payment.payment_date.desc())
            .limit(10)
            .all()
        )
        for p in payments:
            results.append({
                "type": "receipt",
                "id": p.customer_id,
                "receipt_number": p.receipt_number,
                "amount": float(p.amount),
                "name": p.customer.name if p.customer else "Unknown",
                "date": format_date(p.payment_date),
            })

    # Always search customers by name
    customers = (
        Customer.query
        .filter(Customer.name.ilike(f"%{q}%"))
        .order_by(Customer.name)
        .limit(20)
        .all()
    )
    for c in customers:
        results.append({
            "type": "customer",
            "id": c.id,
            "name": c.name,
            "city": c.city,
            "balance": float(c.balance) if c.balance else 0.0,
            "phone": c.phone,
        })

    return jsonify(results)


@bp.route("/route/today")
def route_today():
    """Full route data for today as JSON."""
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
