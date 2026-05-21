"""
Entry point for both development and PyInstaller-packaged distribution.
Sets EMAIL_AGENT_DATA_DIR to the OS-appropriate writable directory,
then starts Flask and auto-opens the browser.
"""
import os
import platform
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def get_data_dir() -> Path:
    """Return the user-specific writable data directory for runtime files."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "EmailAgent"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) / "EmailAgent" if appdata else Path.home() / "EmailAgent"
    else:
        # Linux / development fallback
        base = Path(__file__).parent / "data"
    return base


def _try_shutdown_old_instance(port: int = 5001) -> None:
    """
    If another Email Agent is already running on the preferred port, ask it to shut
    down and wait up to 5 s for the port to become free. Safe to call when nothing
    is running on that port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", port))
        except (ConnectionRefusedError, OSError):
            return  # port is free — nothing to do

    # Port is occupied — ask the old instance to exit gracefully
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/api/shutdown", method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # old version may not have this endpoint — fall through to wait

    # Wait up to 5 s for the port to become free
    for _ in range(10):
        time.sleep(0.5)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return  # success
            except OSError:
                continue
    # Port still occupied — find_free_port will pick the next candidate


def find_free_port(candidates: list[int]) -> int:
    """Return the first port in candidates that is not in use."""
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in candidates: " + str(candidates))


def main() -> None:
    # 1. Set up writable data directory before importing any app modules
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["EMAIL_AGENT_DATA_DIR"] = str(data_dir)

    # 2. Signal any stale instance on the preferred port to exit, then claim it
    _try_shutdown_old_instance(5001)
    port = find_free_port([5001, 5002, 5003, 5004, 5005])

    # 3. Open the browser after a short delay to let Flask start first
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    # 4. Import and start Flask (import after env var is set)
    from app import create_app
    app = create_app()

    # Suppress Flask's startup banner in packaged builds
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False,   # CRITICAL: reloader breaks PyInstaller frozen env
        threaded=True,
    )


if __name__ == "__main__":
    main()
