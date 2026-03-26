"""Lead management routes."""

import csv
import io

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from app import db
from app.helpers import admin_required
from app.models import Customer, ActivityLog

bp = Blueprint("leads", __name__, url_prefix="/leads")


@bp.before_request
@login_required
def before_request():
    """Require login for all lead routes."""
    pass


@bp.route("/")
def index():
    """List customers with status='lead', with optional filters."""
    query = Customer.query.filter(Customer.status == "lead")

    lead_source_filter = request.args.get("lead_source", "").strip()
    if lead_source_filter:
        query = query.filter(Customer.lead_source == lead_source_filter)

    city_filter = request.args.get("city", "").strip()
    if city_filter:
        query = query.filter(Customer.city == city_filter)

    leads = query.order_by(Customer.created_at.desc()).all()

    # Available filter options
    lead_sources = (
        db.session.query(Customer.lead_source)
        .filter(
            Customer.status == "lead",
            Customer.lead_source.isnot(None),
            Customer.lead_source != "",
        )
        .distinct()
        .order_by(Customer.lead_source)
        .all()
    )
    lead_sources = [s[0] for s in lead_sources]

    cities = (
        db.session.query(Customer.city)
        .filter(
            Customer.status == "lead",
            Customer.city.isnot(None),
            Customer.city != "",
        )
        .distinct()
        .order_by(Customer.city)
        .all()
    )
    cities = [c[0] for c in cities]

    return render_template(
        "leads.html",
        leads=leads,
        lead_sources=lead_sources,
        cities=cities,
        lead_source_filter=lead_source_filter,
        city_filter=city_filter,
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    """Create a new lead."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return render_template("leads_form.html", lead=None, editing=False), 400

        lead = Customer(
            name=name,
            address=request.form.get("address", "").strip() or None,
            city=request.form.get("city", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            lead_source=request.form.get("lead_source", "").strip() or None,
            status="lead",
        )
        db.session.add(lead)

        log = ActivityLog(
            customer_id=None,  # will be set after flush
            user_id=current_user.id,
            action="lead_created",
            description=f"Lead '{name}' created.",
        )

        db.session.flush()
        log.customer_id = lead.id
        db.session.add(log)
        db.session.commit()

        flash(f"Lead '{name}' created successfully.", "success")
        return redirect(url_for("leads.index"))

    return render_template("leads_form.html", lead=None, editing=False)


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
def edit(id):
    """Edit an existing lead."""
    lead = db.session.get(Customer, id)
    if lead is None or lead.status != "lead":
        flash("Lead not found.", "error")
        return redirect(url_for("leads.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return render_template("leads_form.html", lead=lead, editing=True), 400

        lead.name = name
        lead.address = request.form.get("address", "").strip() or None
        lead.city = request.form.get("city", "").strip() or None
        lead.phone = request.form.get("phone", "").strip() or None
        lead.notes = request.form.get("notes", "").strip() or None
        lead.lead_source = request.form.get("lead_source", "").strip() or None
        db.session.commit()

        flash(f"Lead '{lead.name}' updated.", "success")
        return redirect(url_for("leads.index"))

    return render_template("leads_form.html", lead=lead, editing=True)


@bp.route("/<int:id>/convert", methods=["POST"])
def convert(id):
    """Convert a lead to an active customer."""
    lead = db.session.get(Customer, id)
    if lead is None or lead.status != "lead":
        flash("Lead not found.", "error")
        return redirect(url_for("leads.index"))

    lead.status = "active"
    lead.lead_source = None

    log = ActivityLog(
        customer_id=lead.id,
        user_id=current_user.id,
        action="lead_converted",
        description=f"Lead '{lead.name}' converted to active customer.",
    )
    db.session.add(log)
    db.session.commit()

    flash(f"'{lead.name}' has been converted to an active customer.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/import-csv", methods=["POST"])
@admin_required
def import_csv():
    """Import leads from a CSV file upload (admin only)."""
    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("No CSV file was uploaded.", "error")
        return redirect(url_for("leads.index"))

    if not csv_file.filename.lower().endswith(".csv"):
        flash("Uploaded file must be a .csv file.", "error")
        return redirect(url_for("leads.index"))

    try:
        stream = io.TextIOWrapper(csv_file.stream, encoding="utf-8-sig")
        reader = csv.DictReader(stream)

        imported = 0
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue

            lead = Customer(
                name=name,
                address=row.get("address", "").strip() or None,
                city=row.get("city", "").strip() or None,
                phone=row.get("phone", "").strip() or None,
                notes=row.get("notes", "").strip() or None,
                lead_source=row.get("lead_source", "").strip() or None,
                status="lead",
            )
            db.session.add(lead)
            imported += 1

        db.session.commit()

        log = ActivityLog(
            customer_id=None,
            user_id=current_user.id,
            action="leads_imported",
            description=f"Imported {imported} leads from CSV.",
        )
        # Use the first imported lead as a reference if available
        if imported > 0:
            last_lead = (
                Customer.query
                .filter(Customer.status == "lead")
                .order_by(Customer.id.desc())
                .first()
            )
            if last_lead:
                log.customer_id = last_lead.id
                db.session.add(log)
                db.session.commit()

        flash(f"Successfully imported {imported} leads.", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Import failed: {exc}", "error")

    return redirect(url_for("leads.index"))
