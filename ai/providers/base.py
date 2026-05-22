from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    def generate(self, user_message: str, system: str, use_persona: bool = False) -> str:
        """
        Generate a response.

        Raises ProviderUnavailableError for soft failures (rate limit, server error,
        network timeout) — the FallbackRouter will try the next provider.

        Raises GenerationError for hard failures (invalid API key, content policy)
        — the FallbackRouter propagates these immediately without trying fallbacks.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider identifier used in log messages."""
