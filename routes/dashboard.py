import app as app_module
from flask import Blueprint, jsonify, render_template

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@dashboard_bp.route("/api/status")
def status():
    return jsonify(app_module.daemon.get_status())


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
    The dashboard polls /setup/api/oauth_status until done, then calls /api/agent/start.
    """
    app_module.daemon.stop()
    from routes.setup import start_oauth_thread
    start_oauth_thread()
    return jsonify({"ok": True})
