# routes/balances.py
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import get_conn

balances_bp = Blueprint("balances", __name__)


@balances_bp.route("/balances")
def balances():
    """Display all customers with outstanding balances"""

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    phone,
                    address,
                    balance_cents,
                    last_visit_at
                FROM customers
                WHERE balance_cents > 0
                ORDER BY balance_cents DESC
                """
            )
            customers = cur.fetchall()

    # ---- Derived stats for the UI ----
    total_customers = len(customers)
    total_owed_cents = sum(c["balance_cents"] for c in customers)
    largest_balance_cents = customers[0]["balance_cents"] if customers else 0

    context = {
        "customers": customers,
        "now": datetime.now(),
        "total_customers": total_customers,
        "total_owed_cents": total_owed_cents,
        "largest_balance_cents": largest_balance_cents,
    }

    return render_template("balances.html", **context)


@balances_bp.post("/balances/record_payment")
def record_payment():
    """Record a payment for a customer"""

    customer_id = request.form.get("customer_id")
    amount_str = request.form.get("amount", "0")
    payment_method = request.form.get("payment_method", "cash")
    notes = request.form.get("notes", "").strip()

    if not customer_id:
        flash("Customer ID is required", "error")
        return redirect(url_for("balances.balances"))

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Payment amount must be greater than zero", "error")
        return redirect(url_for("balances.balances"))

    amount_cents = int(amount * 100)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Fetch customer
            cur.execute(
                "SELECT name, balance_cents FROM customers WHERE id = %s",
                (customer_id,),
            )
            customer = cur.fetchone()

            if not customer:
                flash("Customer not found", "error")
                return redirect(url_for("balances.balances"))

            # Warn but allow overpayment
            if amount_cents > customer["balance_cents"]:
                flash(
                    (
                        f"Payment amount (${amount:.2f}) exceeds "
                        f"current balance (${customer['balance_cents'] / 100:.2f}). "
                        "Balance will go negative."
                    ),
                    "warning",
                )

            # Record payment
            cur.execute(
                """
                INSERT INTO payments (
                    customer_id,
                    amount_cents,
                    note,
                    received_at
                )
                VALUES (%s, %s, %s, NOW())
                """,
                (customer_id, amount_cents, notes or None),
            )

            # Update balance
            cur.execute(
                """
                UPDATE customers
                SET balance_cents = balance_cents - %s
                WHERE id = %s
                """,
                (amount_cents, customer_id),
            )

            conn.commit()

    flash(
        f"Payment of ${amount:.2f} recorded for {customer['name']}",
        "success",
    )
    return redirect(url_for("balances.balances"))
