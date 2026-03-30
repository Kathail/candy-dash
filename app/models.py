"""SQLAlchemy models for Candy Route Planner."""

from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

VALID_CUSTOMER_STATUSES = ("active", "inactive", "lead")
VALID_ROLES = ("owner", "admin", "bookkeeper", "demo")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="owner")
    is_active = db.Column(db.Boolean, default=True)

    route_stops = db.relationship("RouteStop", backref="creator", lazy="dynamic", foreign_keys="RouteStop.created_by")
    payments = db.relationship("Payment", backref="recorder", lazy="dynamic", foreign_keys="Payment.recorded_by")
    activity_logs = db.relationship("ActivityLog", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_demo(self):
        return self.role == "demo"

    @property
    def is_bookkeeper(self):
        return self.role == "bookkeeper"

    @property
    def can_write(self):
        """Returns True if user can create/edit/delete data."""
        return self.role in ("owner", "admin")

    def __repr__(self):
        return f"<User {self.username}>"


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    address = db.Column(db.String(300), nullable=True)
    city = db.Column(db.String(100), nullable=True, index=True)
    phone = db.Column(db.String(30), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    balance = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    tax_exempt = db.Column(db.Boolean, default=False)
    lead_source = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    route_stops = db.relationship("RouteStop", backref="customer", lazy="dynamic")
    payments = db.relationship("Payment", backref="customer", lazy="dynamic", order_by="Payment.payment_date.desc()")
    activity_logs = db.relationship("ActivityLog", backref="customer", lazy="dynamic", order_by="ActivityLog.created_at.desc()")

    def __repr__(self):
        return f"<Customer {self.name}>"


class RouteStop(db.Model):
    __tablename__ = "route_stops"
    __table_args__ = (
        db.Index("ix_route_stops_date_customer", "route_date", "customer_id"),
        db.Index("ix_route_stops_date_completed", "route_date", "completed"),
    )

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    route_date = db.Column(db.Date, nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return f"<RouteStop {self.customer.name if self.customer else self.customer_id} on {self.route_date}>"


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    invoice_number = db.Column(db.String(50), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="unpaid")  # unpaid, paid, void
    payment_type = db.Column(db.String(20), nullable=True)  # set when paid
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", backref=db.backref("invoices", lazy="dynamic", order_by="Invoice.invoice_date.desc()"))
    creator = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<Invoice {self.invoice_number or self.id} ${self.amount}>"


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    customer = db.relationship("Customer", backref=db.backref("note_entries", lazy="dynamic", order_by="Note.created_at.desc()"))
    user = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<Note {self.id} for customer {self.customer_id}>"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    amount_sold = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    payment_type = db.Column(db.String(20), nullable=True, default="cash")  # cash, cheque, credit, debit, etransfer, other
    payment_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    receipt_number = db.Column(db.String(20), unique=True, nullable=False)
    previous_balance = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Payment {self.receipt_number} ${self.amount}>"


class RecurringStop(db.Model):
    __tablename__ = "recurring_stops"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    interval_days = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", backref=db.backref("recurring_stops", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by])

    def matches(self, target_date):
        """Return True if this schedule falls on target_date."""
        if not self.is_active:
            return False
        delta = (target_date - self.start_date).days
        if delta < 0:
            return False
        if self.end_date and target_date > self.end_date:
            return False
        return delta % self.interval_days == 0

    @property
    def frequency_label(self):
        d = self.interval_days
        if d == 1:
            return "Daily"
        if d == 7:
            return "Weekly"
        if d == 14:
            return "Biweekly"
        if d in (28, 30, 31):
            return "Monthly"
        return f"Every {d} days"

    def __repr__(self):
        return f"<RecurringStop customer={self.customer_id} every {self.interval_days}d>"


class RecurringSkip(db.Model):
    __tablename__ = "recurring_skips"

    id = db.Column(db.Integer, primary_key=True)
    recurring_stop_id = db.Column(db.Integer, db.ForeignKey("recurring_stops.id"), nullable=False, index=True)
    skip_date = db.Column(db.Date, nullable=False)

    recurring_stop = db.relationship("RecurringStop", backref=db.backref("skips", lazy="dynamic"))

    def __repr__(self):
        return f"<RecurringSkip recurring={self.recurring_stop_id} date={self.skip_date}>"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f"<ActivityLog {self.action} for customer {self.customer_id}>"


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<AdminAuditLog {self.action} by user {self.user_id}>"
