import app as app_module
from flask import Blueprint, jsonify, render_template
from storage.app_config import config_exists, load_config

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@dashboard_bp.route("/api/status")
def status():
    data = app_module.daemon.get_status()
    # Expose poll interval so the dashboard can show "polls every N min"
    if config_exists():
        try:
            data["poll_interval_seconds"] = load_config().get("poll_interval_seconds", 300)
        except Exception:
            data["poll_interval_seconds"] = 300
    return jsonify(data)


@dashboard_bp.route("/api/agent/start", methods=["POST"])
def agent_start():
    app_module.daemon.start()
    return jsonify({"ok": True})


@dashboard_bp.route("/api/agent/stop", methods=["POST"])
def agent_stop():
    app_module.daemon.stop()
    return jsonify({"ok": True})


@dashboard_bp.route("/api/agent/reconnect", methods=["POST"])
def agent_reconnect():
    """
    Stop the daemon, re-run the Gmail OAuth flow, then restart.
    Called when the token has expired (typically after 7 days in Testing mode).
    """
    app_module.daemon.stop()
    from routes.setup import start_oauth_thread
    start_oauth_thread()
    return jsonify({"ok": True})
