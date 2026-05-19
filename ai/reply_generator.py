import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from ai.prompts import build_system_prompt
from config import Settings
from exceptions import GenerationError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2  # seconds


class ReplyGenerator:
    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._system_prompt = build_system_prompt(settings.persona_prompt)

    def generate(self, user_message: str) -> str:
        """
        Generate an email body from the given user message.
        Retries on rate limit (429). Raises GenerationError on unrecoverable failures.
        """
        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt,
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=user_message,
                    config=config,
                )
                text = response.text
                if not text:
                    raise GenerationError("Gemini returned an empty response.")
                return text.strip()

            except ClientError as exc:
                code = exc.code if hasattr(exc, "code") else 0
                status = getattr(exc, "status", "")

                if code == 429 or "RESOURCE_EXHAUSTED" in str(status):
                    if attempt < _MAX_RETRIES:
                        wait = _INITIAL_BACKOFF * (2 ** attempt)
                        logger.warning("Gemini rate limit. Retrying in %ds...", wait)
                        time.sleep(wait)
                        continue
                    raise GenerationError("Gemini rate limit exceeded after retries.") from exc

                if code == 401 or "UNAUTHENTICATED" in str(status):
                    raise GenerationError(
                        "Invalid Gemini API key. Check GEMINI_API_KEY in your .env file."
                    ) from exc

                raise GenerationError(f"Gemini client error ({code}): {exc}") from exc

            except ServerError as exc:
                raise GenerationError(f"Gemini server error (5xx): {exc}") from exc

        # Unreachable, but satisfies type checker
        raise GenerationError("Gemini generation failed after all retries.")
