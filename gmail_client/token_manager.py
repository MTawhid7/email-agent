"""
Proactive OAuth2 token lifecycle manager.

Runs a background thread that checks token expiry every 30 seconds and
refreshes proactively 5 minutes before expiry, so the Gmail API and IMAP
connections never encounter an expired token mid-operation.

Notifies registered callbacks (e.g. ImapIdleWatcher) when a new token is
available so they can reconnect with the fresh credentials.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from exceptions import AuthError, TokenRefreshError
from gmail_client.auth import get_credentials, _save_token

logger = logging.getLogger(__name__)

_REFRESH_AHEAD_SECONDS = 300   # refresh 5 minutes before expiry
_CHECK_INTERVAL_SECONDS = 30   # how often the refresh loop wakes up
_RETRY_AFTER_FAILURE    = 60   # seconds to wait before retrying after a failure


class TokenManager:
    """
    Thread-safe OAuth2 credential manager with proactive background refresh.

    Usage:
        tm = TokenManager(credentials_path, token_path)
        tm.start()
        creds = tm.get_credentials()
        tm.register_refresh_callback(lambda c: imap.reconnect(c.token))
    """

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._refresh_thread: Optional[threading.Thread] = None
        self._callbacks: list[Callable[[Credentials], None]] = []
        self._creds: Optional[Credentials] = None
        self._failed_at: float = 0.0

        # Load credentials immediately (synchronous, safe on main thread)
        self._creds = get_credentials(
            credentials_path=credentials_path,
            token_path=token_path,
            allow_oauth_flow=False,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background refresh thread."""
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name="TokenManager",
            daemon=True,
        )
        self._refresh_thread.start()

    def stop(self) -> None:
        """Signal the refresh thread to exit."""
        self._stop_event.set()

    def get_credentials(self) -> Credentials:
        """Return current credentials. Thread-safe."""
        with self._lock:
            return self._creds

    def register_refresh_callback(self, cb: Callable[[Credentials], None]) -> None:
        """Register a callback invoked with fresh credentials after each successful refresh."""
        self._callbacks.append(cb)

    # ── Background refresh loop ────────────────────────────────────────────────

    def _refresh_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_CHECK_INTERVAL_SECONDS)
            if self._stop_event.is_set():
                break
            try:
                self._maybe_refresh()
            except TokenRefreshError as exc:
                # Refresh token revoked — surface to daemon via _set_error
                logger.error("OAuth refresh token revoked: %s", exc)
                raise  # propagates out of the daemon thread; daemon calls _set_error
            except Exception as exc:
                logger.warning("Token refresh failed (will retry in %ds): %s",
                               _RETRY_AFTER_FAILURE, exc)
                self._failed_at = datetime.now(tz=timezone.utc).timestamp()

    def _maybe_refresh(self) -> None:
        """Refresh the token if it is within 5 minutes of expiry."""
        import time
        # If we recently failed, wait before retrying
        if self._failed_at:
            elapsed = datetime.now(tz=timezone.utc).timestamp() - self._failed_at
            if elapsed < _RETRY_AFTER_FAILURE:
                return
            self._failed_at = 0.0

        with self._lock:
            creds = self._creds

        if creds is None or not creds.refresh_token:
            return

        # Determine seconds until expiry
        expiry = getattr(creds, "expiry", None)
        if expiry is None:
            return  # no expiry info — nothing to do

        # Ensure expiry is timezone-aware for comparison
        now = datetime.now(tz=timezone.utc)
        if expiry.tzinfo is None:
            from datetime import timezone as _tz
            expiry = expiry.replace(tzinfo=_tz.utc)

        seconds_left = (expiry - now).total_seconds()
        if seconds_left > _REFRESH_AHEAD_SECONDS:
            return  # plenty of time left

        logger.info("Token expires in %.0fs — refreshing proactively", seconds_left)
        self._do_refresh(creds)

    def _do_refresh(self, creds: Credentials) -> None:
        """Perform the actual token refresh and notify callbacks."""
        try:
            creds.refresh(Request())
        except Exception as exc:
            err_str = str(exc).lower()
            if "invalid_grant" in err_str or "token has been expired or revoked" in err_str:
                raise TokenRefreshError(
                    "Gmail refresh token revoked. Click 'Re-connect Gmail' on the Dashboard."
                ) from exc
            raise  # other network errors — let caller handle retry

        _save_token(creds, self._token_path)
        with self._lock:
            self._creds = creds
        self._notify_callbacks(creds)
        logger.info("OAuth token refreshed successfully.")

    def _notify_callbacks(self, creds: Credentials) -> None:
        for cb in self._callbacks:
            try:
                cb(creds)
            except Exception as exc:
                logger.warning("Token refresh callback error: %s", exc)
