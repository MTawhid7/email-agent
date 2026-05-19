import sys
from pathlib import Path

from flask import Flask, redirect, request, url_for

from agent.daemon import AgentDaemon
from storage.app_config import config_exists

# Module-level daemon singleton — persists for the lifetime of the process
daemon = AgentDaemon()

_SETUP_PATHS = {"/setup/step1", "/setup/step2", "/setup/step3", "/setup/step4"}
_API_PATHS_PREFIX = "/api/oauth_status"


def _resource_path(relative: str) -> str:
    """Resolve path for both dev and PyInstaller frozen environments."""
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

    # ── Blueprints ─────────────────────────────────────────────────────────────
    from routes.setup import setup_bp
    from routes.dashboard import dashboard_bp
    from routes.settings import settings_bp
    from routes.contacts import contacts_bp
    from routes.bulk import bulk_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(bulk_bp)

    # ── Guard: redirect to setup if not configured ─────────────────────────────
    @app.before_request
    def require_setup():
        path = request.path
        # Allow setup pages, static files, and the OAuth status API through
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

    return app
