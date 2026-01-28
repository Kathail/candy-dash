import os
from datetime import date, datetime

from flask import Flask


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # Register routes
    from routes.balances import balances_bp
    from routes.calendar import calendar_bp
    from routes.customers import customers_bp
    from routes.dashboard import dashboard_bp
    from routes.route import route_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(route_bp)
    app.register_blueprint(
        calendar_bp, url_prefix="/calendar"
    )  # ← FIXED HERE: added url_prefix
    app.register_blueprint(balances_bp)

    @app.context_processor
    def inject_globals():
        """Inject commonly used variables into all templates"""
        return {"today": date.today(), "now": datetime.now()}

    @app.errorhandler(404)
    def not_found(e):
        return (
            """
        <div style="font-family: system-ui; max-width: 600px; margin: 100px auto; text-align: center;">
            <h1 style="font-size: 72px; margin: 0; color: #3b82f6;">404</h1>
            <p style="font-size: 24px; color: #6b7280; margin: 20px 0;">Page not found</p>
            <a href="/" style="display: inline-block; background: #3b82f6; color: white; padding: 12px 24px;
               border-radius: 8px; text-decoration: none; margin-top: 20px;">
                Go to Dashboard
            </a>
        </div>
        """,
            404,
        )

    @app.errorhandler(500)
    def internal_error(e):
        return (
            """
        <div style="font-family: system-ui; max-width: 600px; margin: 100px auto; text-align: center;">
            <h1 style="font-size: 72px; margin: 0; color: #ef4444;">500</h1>
            <p style="font-size: 24px; color: #6b7280; margin: 20px 0;">Internal Server Error</p>
            <p style="color: #9ca3af;">Something went wrong. Please try again.</p>
            <a href="/" style="display: inline-block; background: #3b82f6; color: white; padding: 12px 24px;
               border-radius: 8px; text-decoration: none; margin-top: 20px;">
                Go to Dashboard
            </a>
        </div>
        """,
            500,
        )

    return app


if __name__ == "__main__":
    app = create_app()
    print("\n" + "=" * 50)
    print("🍬 Candy Dash - Route Planner")
    print("=" * 50)
    # Get port from environment (Render sets PORT; fallback to 5000 for local)
    port = int(os.environ.get("PORT", 5000))
    print(f"Running on: http://0.0.0.0:{port}")
    print("Press CTRL+C to quit")
    print("=" * 50 + "\n")
    # Bind to 0.0.0.0 and dynamic port; debug off in prod
    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG", "False").lower() == "true",
    )
