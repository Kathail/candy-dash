"""SQLAlchemy models for Candy Route Planner."""

from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="sales")
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

    def __repr__(self):
        return f"<User {self.username}>"


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    balance = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="active")
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

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    route_date = db.Column(db.Date, nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return f"<RouteStop {self.customer.name if self.customer else self.customer_id} on {self.route_date}>"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    receipt_number = db.Column(db.String(20), unique=True, nullable=False)
    previous_balance = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Payment {self.receipt_number} ${self.amount}>"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ActivityLog {self.action} for customer {self.customer_id}>"
