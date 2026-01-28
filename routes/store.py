from datetime import date
from typing import Any, Dict, List, Optional

from .db import get_conn

# ============================================================================
# Customers
# ============================================================================


def get_customers() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, phone, address, notes, balance_cents, last_visit_at
                FROM customers
                ORDER BY name
                """
            )
            return cur.fetchall()


def get_customer(customer_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, phone, address, notes, balance_cents, last_visit_at
                FROM customers
                WHERE id = %s
                """,
                (customer_id,),
            )
            return cur.fetchone()


def create_customer(
    name: str,
    phone: str = "",
    address: str = "",
    balance_cents: int = 0,
    notes: str = "",
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO customers (name, phone, address, balance_cents, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    name.strip(),
                    phone.strip() or None,
                    address.strip() or None,
                    balance_cents,
                    notes.strip() or None,
                ),
            )
            customer_id = cur.fetchone()["id"]
            conn.commit()
            return customer_id


def update_customer(
    customer_id: int,
    *,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    balance_cents: Optional[int] = None,
) -> bool:
    updates = []
    params = []

    if name is not None:
        updates.append("name = %s")
        params.append(name.strip())

    if phone is not None:
        updates.append("phone = %s")
        params.append(phone.strip() or None)

    if address is not None:
        updates.append("address = %s")
        params.append(address.strip() or None)

    if notes is not None:
        updates.append("notes = %s")
        params.append(notes.strip() or None)

    if balance_cents is not None:
        updates.append("balance_cents = %s")
        params.append(balance_cents)

    if not updates:
        return False

    params.append(customer_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE customers SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
            conn.commit()

    return True


def adjust_customer_balance(customer_id: int, delta_cents: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE customers
                SET balance_cents = balance_cents + %s
                WHERE id = %s
                """,
                (delta_cents, customer_id),
            )
            conn.commit()


def delete_customer(customer_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
            conn.commit()


# ============================================================================
# Routes & Stops
# ============================================================================


def get_or_create_route(route_date: date) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO routes (route_date)
                VALUES (%s)
                ON CONFLICT (route_date) DO UPDATE
                SET route_date = EXCLUDED.route_date
                RETURNING id
                """,
                (route_date,),
            )
            route_id = cur.fetchone()["id"]
            conn.commit()
            return route_id


def get_or_create_today_route() -> int:
    return get_or_create_route(date.today())


def get_today_route_stops() -> List[Dict[str, Any]]:
    today = date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    rs.id              AS stop_id,
                    rs.customer_id,
                    c.name,
                    c.phone            AS customer_phone,
                    c.address          AS customer_address,
                    c.balance_cents    AS customer_balance,
                    c.notes            AS customer_notes,
                    rs.completed,
                    rs.completed_at,
                    rs.notes,
                    rs.stop_order
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                JOIN customers c ON rs.customer_id = c.id
                WHERE r.route_date = %s
                ORDER BY rs.stop_order
                """,
                (today,),
            )
            return cur.fetchall()


def add_customer_to_route(route_date: date, customer_id: int) -> None:
    route_id = get_or_create_route(route_date)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM route_stops
                WHERE route_id = %s AND customer_id = %s
                """,
                (route_id, customer_id),
            )
            if cur.fetchone():
                return

            cur.execute(
                """
                SELECT COALESCE(MAX(stop_order), -1) + 1 AS next_order
                FROM route_stops
                WHERE route_id = %s
                """,
                (route_id,),
            )
            next_order = cur.fetchone()["next_order"]

            cur.execute(
                """
                INSERT INTO route_stops (route_id, customer_id, stop_order)
                VALUES (%s, %s, %s)
                """,
                (route_id, customer_id, next_order),
            )
            conn.commit()


def add_customer_to_today_route(customer_id: int) -> None:
    add_customer_to_route(date.today(), customer_id)


def complete_stop(stop_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE route_stops
                SET completed = true, completed_at = NOW()
                WHERE id = %s
                RETURNING customer_id
                """,
                (stop_id,),
            )
            result = cur.fetchone()

            if not result:
                return

            customer_id = result["customer_id"]

            cur.execute(
                "UPDATE customers SET last_visit_at = CURRENT_DATE WHERE id = %s",
                (customer_id,),
            )

            cur.execute(
                """
                INSERT INTO visits (customer_id, route_stop_id)
                VALUES (%s, %s)
                """,
                (customer_id, stop_id),
            )

            conn.commit()


def remove_stop(stop_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM route_stops WHERE id = %s", (stop_id,))
            conn.commit()


def update_stop_notes(stop_id: int, notes: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE route_stops SET notes = %s WHERE id = %s",
                (notes.strip() or None, stop_id),
            )
            conn.commit()


# ============================================================================
# Dashboard
# ============================================================================


def get_dashboard_stats() -> Dict[str, Any]:
    today = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM customers")
            total_customers = cur.fetchone()["total"]

            cur.execute(
                "SELECT COUNT(*) AS owed FROM customers WHERE balance_cents > 0"
            )
            total_owed_customers = cur.fetchone()["owed"]

            cur.execute("SELECT SUM(balance_cents) AS total FROM customers")
            total_owed_cents = cur.fetchone()["total"] or 0

            cur.execute(
                """
                SELECT COUNT(*) AS completed
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                WHERE r.route_date = %s AND rs.completed = true
                """,
                (today,),
            )
            completed_today = cur.fetchone()["completed"]

            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM route_stops rs
                JOIN routes r ON rs.route_id = r.id
                WHERE r.route_date = %s
                """,
                (today,),
            )
            total_stops_today = cur.fetchone()["total"]

            return {
                "total_customers": total_customers,
                "total_owed_customers": total_owed_customers,
                "total_owed_cents": total_owed_cents,
                "completed_today": completed_today,
                "total_stops_today": total_stops_today,
            }
