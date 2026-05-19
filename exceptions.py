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


class ConfigError(EmailAgentError):
    """Missing or invalid configuration."""
