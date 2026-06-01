import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from ai.providers.base import LLMProvider
from core.exceptions import GenerationError, ProviderUnavailableError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2  # seconds


class GeminiProvider(LLMProvider):
    """
    Primary LLM provider using Google Gemini.
    Retries on 429 with exponential backoff.
    Raises ProviderUnavailableError on exhausted retries or 5xx so the
    FallbackRouter can try the next provider.
    Raises GenerationError (hard) on 401 — a bad key won't work after failover.
    """

    def __init__(self, api_key: str, model: str, system_prompt: str = "") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._system_prompt = system_prompt

    @property
    def name(self) -> str:
        return "gemini"

    def generate(self, user_message: str, system: str, use_persona: bool = False) -> str:
        instruction = self._system_prompt if use_persona else system
        config = types.GenerateContentConfig(system_instruction=instruction)

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=user_message,
                    config=config,
                )
                text = response.text
                if not text:
                    raise ProviderUnavailableError("Gemini returned an empty response.")
                return text.strip()

            except ClientError as exc:
                code = exc.code if hasattr(exc, "code") else 0
                status = getattr(exc, "status", "")

                if code == 429 or "RESOURCE_EXHAUSTED" in str(status):
                    if attempt < _MAX_RETRIES:
                        wait = _INITIAL_BACKOFF * (2 ** attempt)
                        logger.warning("Gemini rate limit. Retrying in %ds…", wait)
                        time.sleep(wait)
                        continue
                    raise ProviderUnavailableError(
                        "Gemini rate limit exceeded after retries."
                    ) from exc

                if code == 401 or "UNAUTHENTICATED" in str(status):
                    raise GenerationError(
                        "Invalid Gemini API key. Check your key in Settings."
                    ) from exc

                raise ProviderUnavailableError(
                    f"Gemini client error ({code}): {exc}"
                ) from exc

            except ServerError as exc:
                # 5xx — treat as soft failure so fallback can be tried
                raise ProviderUnavailableError(
                    f"Gemini server error (5xx): {exc}"
                ) from exc

        raise ProviderUnavailableError("Gemini generation failed after all retries.")
