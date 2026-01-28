from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from .store import (
    create_customer,
    delete_customer,
    get_customer,
    get_customers,
)

customers_bp = Blueprint("customers", __name__)


@customers_bp.route("/customers")
def customers():
    return render_template("customers.html", customers=get_customers())


@customers_bp.route("/api/customers/json")
def get_customers_json():
    """Return all customers as JSON for route/calendar modals"""
    customers = get_customers()
    return jsonify(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "phone": c.get("phone"),
                "address": c.get("address"),
                "balance_cents": c.get("balance_cents", 0),
                "last_visit_at": c.get("last_visit_at").strftime("%Y-%m-%d")
                if c.get("last_visit_at")
                else None,
            }
            for c in customers
        ]
    )


@customers_bp.post("/customers/add")
def customer_add():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    notes = request.form.get("notes", "").strip()
    balance = request.form.get("balance", "0")

    if not name:
        flash("Name is required", "error")
        return redirect(url_for("customers.customers"))

    try:
        balance_cents = int(float(balance) * 100)
    except (ValueError, TypeError):
        balance_cents = 0

    create_customer(name, phone, address, balance_cents, notes)
    flash("Customer added successfully", "success")
    return redirect(url_for("customers.customers"))


@customers_bp.post("/customers/edit/<int:customer_id>")
def customer_edit(customer_id: int):
    customer = get_customer(customer_id)
    if not customer:
        flash("Customer not found", "error")
        return redirect(url_for("customers.customers"))

    name = request.form.get("name", customer["name"]).strip()
    phone = request.form.get("phone", customer["phone"] or "").strip()
    address = request.form.get("address", customer["address"] or "").strip()
    notes = request.form.get("notes", customer["notes"] or "").strip()
    balance = request.form.get("balance", str(customer["balance_cents"] / 100))

    try:
        balance_cents = int(float(balance) * 100)
    except (ValueError, TypeError):
        balance_cents = customer["balance_cents"]

    updates = []
    params = []

    if name != customer["name"]:
        updates.append("name = %s")
        params.append(name)
    if phone != (customer["phone"] or ""):
        updates.append("phone = %s")
        params.append(phone or None)
    if address != (customer["address"] or ""):
        updates.append("address = %s")
        params.append(address or None)
    if notes != (customer["notes"] or ""):
        updates.append("notes = %s")
        params.append(notes or None)
    if balance_cents != customer["balance_cents"]:
        updates.append("balance_cents = %s")
        params.append(balance_cents)

    if updates:
        params.append(customer_id)
        from .db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE customers SET {', '.join(updates)} WHERE id = %s",
                    tuple(params),
                )
                conn.commit()
        flash("Customer updated", "success")
    else:
        flash("No changes made", "info")

    return redirect(url_for("customers.customers"))


@customers_bp.post("/customers/delete/<int:customer_id>")
def customer_delete(customer_id: int):
    delete_customer(customer_id)
    flash("Customer deleted", "success")
    return redirect(url_for("customers.customers"))
