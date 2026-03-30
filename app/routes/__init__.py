"""Blueprint registration."""
from flask import Flask

def register_blueprints(app: Flask):
    from app.routes.auth import bp as auth_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.customers import bp as customers_bp
    from app.routes.route import bp as route_bp
    from app.routes.planner import bp as planner_bp
    from app.routes.balances import bp as balances_bp
    from app.routes.analytics import bp as analytics_bp
    from app.routes.leads import bp as leads_bp
    from app.routes.reports import bp as reports_bp
    from app.routes.api import bp as api_bp
    from app.routes.exports import bp as exports_bp
    from app.routes.bookkeeper import bp as bookkeeper_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(route_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(balances_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(bookkeeper_bp)
