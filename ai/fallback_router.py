import logging
from typing import Optional

from ai.providers.base import LLMProvider
from exceptions import GenerationError, ProviderUnavailableError

logger = logging.getLogger(__name__)


class FallbackRouter:
    """
    Tries LLM providers in priority order, moving to the next on soft failures.

    Soft failures (ProviderUnavailableError): rate limit, server error, timeout.
      → log warning, try next provider.

    Hard failures (GenerationError that is NOT ProviderUnavailableError): invalid API
      key, content policy violation.
      → propagate immediately without trying further providers.

    If all providers fail, raises GenerationError with a combined summary.
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackRouter requires at least one provider.")
        self._providers = providers

    def generate(self, user_message: str, system: str, use_persona: bool = False) -> str:
        last_error: Optional[Exception] = None
        primary_name = self._providers[0].name

        for provider in self._providers:
            try:
                result = provider.generate(user_message, system, use_persona)
                if provider.name != primary_name:
                    logger.warning(
                        "Used fallback provider '%s' (primary '%s' was unavailable)",
                        provider.name,
                        primary_name,
                    )
                return result
            except ProviderUnavailableError as exc:
                logger.warning(
                    "Provider '%s' unavailable: %s — trying next provider",
                    provider.name,
                    exc,
                )
                last_error = exc
                continue
            except GenerationError:
                # Hard failure — do not try other providers
                raise

        raise GenerationError(
            f"All LLM providers failed. "
            f"Last error from '{self._providers[-1].name}': {last_error}"
        ) from last_error
