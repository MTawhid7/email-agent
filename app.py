import sys
from pathlib import Path

from flask import Flask, redirect, request, url_for

from agent.daemon import AgentDaemon
from agent.queue import review_queue  # noqa: F401 — re-exported for routes
from storage.app_config import config_exists, get_token_path

daemon = AgentDaemon()


def _resource_path(relative: str) -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return str(base / relative)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=_resource_path("templates"),
        static_folder=_resource_path("static"),
    )
    app.secret_key = "email-agent-local-secret"

    from routes.setup import setup_bp
    from routes.dashboard import dashboard_bp
    from routes.settings import settings_bp
    from routes.contacts import contacts_bp
    from routes.bulk import bulk_bp
    from routes.review import review_bp
    from routes.templates_route import templates_bp
    from routes.debug import debug_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(bulk_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(debug_bp)

    @app.before_request
    def require_setup():
        path = request.path
        if (
            path.startswith("/setup")
            or path.startswith("/static")
            or path == "/api/oauth_status"
        ):
            return None
        if not config_exists():
            return redirect(url_for("setup.step1"))
        return None

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.dashboard"))

    # Auto-start the daemon if the user has already completed setup.
    # This triggers the macOS network access prompt immediately on launch
    # and ensures the first inbox check happens right away instead of waiting
    # for the user to click "Start Agent".
    if config_exists() and Path(get_token_path()).exists():
        daemon.start()

    return app
