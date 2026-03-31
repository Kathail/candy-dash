"""Public-facing routes — landing page, no auth required."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user

bp = Blueprint("public", __name__, url_prefix="")


@bp.route("/")
def index():
    """Landing page for anonymous users, redirect to dashboard if logged in."""
    if current_user.is_authenticated and not request.args.get("preview"):
        return redirect(url_for("dashboard.index"))
    return render_template("public/index.html")
