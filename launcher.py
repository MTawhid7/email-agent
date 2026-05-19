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

    # 2. Find an available port
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
