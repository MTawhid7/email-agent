class EmailAgentError(Exception):
    """Base exception for all email agent errors."""


class AuthError(EmailAgentError):
    """OAuth2 authentication failures."""


class GmailAPIError(EmailAgentError):
    """Unexpected Gmail HTTP errors."""


class GmailPermissionError(GmailAPIError):
    """403 Forbidden from Gmail API."""


class GenerationError(EmailAgentError):
    """Gemini API generation failures."""


class ProviderUnavailableError(GenerationError):
    """Soft failure — this LLM provider is temporarily unavailable; try the next one."""


class ConfigError(EmailAgentError):
    """Missing or invalid configuration."""


class TokenRefreshError(AuthError):
    """OAuth refresh token revoked — user must re-authenticate via the dashboard."""


class HistoryExpiredError(GmailAPIError):
    """Gmail historyId is older than 30 days — caller must fall back to a full inbox scan."""
