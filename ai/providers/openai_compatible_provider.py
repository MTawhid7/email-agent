"""
OpenAI-compatible provider.

Works with any API that implements the OpenAI chat completions interface:
  - OpenAI:   base_url="https://api.openai.com/v1",        model="gpt-4o-mini"
  - Groq:     base_url="https://api.groq.com/openai/v1",   model="llama-3.3-70b-versatile"
  - xAI Grok: base_url="https://api.x.ai/v1",             model="grok-3-mini"
  - Mistral:  base_url="https://api.mistral.ai/v1",        model="mistral-small-latest"

Uses httpx directly — no openai SDK dependency.
"""
import logging

import httpx

from ai.providers.base import LLMProvider
from exceptions import GenerationError, ProviderUnavailableError

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0  # seconds


class OpenAICompatibleProvider(LLMProvider):
    """
    LLM provider for any OpenAI-compatible REST API.
    Raises ProviderUnavailableError on 429 / 5xx / network errors.
    Raises GenerationError (hard) on 401 or content-filter violations.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        system_prompt: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._system_prompt = system_prompt
        # Determine a short display name from the base URL for logging
        self._display_name = base_url.split("//")[-1].split("/")[0].split(".")[0]

    @property
    def name(self) -> str:
        return self._display_name

    def generate(self, user_message: str, system: str, use_persona: bool = False) -> str:
        instruction = self._system_prompt if use_persona else system
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_message},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"{self.name} request timed out after {_TIMEOUT}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                f"{self.name} connection failed: {exc}"
            ) from exc

        if resp.status_code == 401:
            raise GenerationError(
                f"{self.name}: invalid API key (401). Check your key in Settings."
            )
        if resp.status_code == 429:
            raise ProviderUnavailableError(
                f"{self.name} rate limit (429)."
            )
        if resp.status_code >= 500:
            raise ProviderUnavailableError(
                f"{self.name} server error ({resp.status_code})."
            )
        if resp.status_code != 200:
            body = resp.text[:200]
            # Content policy violation is a hard failure
            if "content_filter" in body or "content_policy" in body:
                raise GenerationError(f"{self.name} content policy violation.")
            raise ProviderUnavailableError(
                f"{self.name} unexpected status {resp.status_code}: {body}"
            )

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderUnavailableError(
                f"{self.name} response parse error: {exc}"
            ) from exc

        if not text:
            raise ProviderUnavailableError(f"{self.name} returned an empty response.")

        return text
