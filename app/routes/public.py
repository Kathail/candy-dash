"""Public-facing routes — landing page, no auth required."""

from urllib.parse import quote

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user

bp = Blueprint("public", __name__, url_prefix="")

CONTACT_EMAIL = "sales@northernsweetsupply.ca"


@bp.route("/")
def index():
    """Landing page for anonymous users, redirect to dashboard if logged in."""
    if current_user.is_authenticated and not request.args.get("preview"):
        return redirect(url_for("dashboard.index"))
    return render_template("public/index.html")


@bp.route("/contact", methods=["POST"])
def contact():
    """Build a mailto: link from the form and redirect to it."""
    store_name = request.form.get("store_name", "").strip()
    location = request.form.get("location", "").strip()
    contact_name = request.form.get("contact_name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    message = request.form.get("message", "").strip()

    subject = f"New Account Request: {store_name or contact_name or 'Website'}"

    body = f"""Hi Northern Sweet Supply,

I'd like to set up an account.

Store Name: {store_name or '(not provided)'}
Location: {location or '(not provided)'}
Contact: {contact_name or '(not provided)'}
Phone: {phone or '(not provided)'}
Email: {email or '(not provided)'}

{message}
"""

    mailto = f"mailto:{CONTACT_EMAIL}?subject={quote(subject)}&body={quote(body)}"
    return redirect(mailto)
