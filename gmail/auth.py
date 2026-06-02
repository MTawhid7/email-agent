import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from core.exceptions import AuthError

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",  # required for IMAP XOAUTH2
]
_TOKEN_PATH = "credentials/token.json"


def get_credentials(
    credentials_path: str,
    token_path: str = _TOKEN_PATH,
    allow_oauth_flow: bool = True,
) -> Credentials:
    """
    Return valid Gmail OAuth2 credentials.

    allow_oauth_flow=True  (setup wizard): open browser for consent if needed.
    allow_oauth_flow=False (daemon):        raise AuthError immediately if no
                                            valid token exists — never block.
    """
    if not os.path.exists(credentials_path):
        raise AuthError(
            f"Gmail credentials file not found: '{credentials_path}'. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    creds: Credentials | None = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, token_path)
            return creds
        except Exception:
            creds = None

    # No valid token available.
    if not allow_oauth_flow:
        raise AuthError(
            "Gmail token missing or expired. "
            "Click 'Re-connect Gmail' on the Dashboard to re-authorise."
        )

    # Setup wizard path: open browser for consent.
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def _save_token(creds: Credentials, token_path: str) -> None:
    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())
