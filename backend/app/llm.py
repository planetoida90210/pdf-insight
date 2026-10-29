"""LLM providers: Gemini (default) and Anthropic with structured output."""

from __future__ import annotations

import base64
import io
import json
import logging
from collections.abc import Callable
from typing import Any, NoReturn, Protocol

from PIL import Image

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.prompts import VISION_PROMPT
from app.schema import LlmAnalysis, llm_json_schema

logger = logging.getLogger("pdf_insight")

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"


class LlmTransport(Protocol):
    def complete(self, *, system: str, user: str) -> dict[str, Any]: ...

    def transcribe(self, image: Image.Image) -> str: ...


def resolve_model(settings: Settings) -> str:
    return settings.resolved_model


def create_transport(settings: Settings) -> LlmTransport:
    model = resolve_model(settings)
    if settings.llm_provider == "anthropic":
        key = settings.anthropic_api_key
        if key is None or not key.get_secret_value():
            raise ApiError(ErrorCode.AI_UNAVAILABLE, "Brak klucza ANTHROPIC_API_KEY.")
        return AnthropicTransport(
            api_key=key.get_secret_value(),
            model=model,
            timeout=settings.llm_timeout_seconds,
        )
    key = settings.gemini_api_key
    if key is None or not key.get_secret_value():
        raise ApiError(ErrorCode.AI_UNAVAILABLE, "Brak klucza GEMINI_API_KEY.")
    return GeminiTransport(
        api_key=key.get_secret_value(),
        model=model,
        timeout=settings.llm_timeout_seconds,
    )


class GeminiTransport:
    """Interactions API: JSON schema + thinking_level=low (ai.google.dev, 2026-10)."""

    def __init__(self, *, api_key: str, model: str, timeout: float) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.timeout = timeout

    def complete(self, *, system: str, user: str) -> dict[str, Any]:
        try:
            interaction = self._client.interactions.create(
                model=self.model,
                input=f"{system}\n\n{user}",
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": llm_json_schema(),
                },
                generation_config={"thinking_level": "low"},
                timeout=self.timeout,
            )
        except Exception as error:
            _map_provider_error(error)
        text = getattr(interaction, "output_text", None) or ""
        if not text:
            raise ApiError(ErrorCode.AI_INVALID_RESPONSE)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ApiError(ErrorCode.AI_INVALID_RESPONSE) from error
        if not isinstance(data, dict):
            raise ApiError(ErrorCode.AI_INVALID_RESPONSE)
        return data

    def transcribe(self, image: Image.Image) -> str:
        payload = _image_b64(image)
        try:
            interaction = self._client.interactions.create(
                model=self.model,
                input=[
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image", "data": payload, "mime_type": "image/png"},
                ],
                generation_config={"thinking_level": "low"},
                timeout=self.timeout,
            )
        except Exception as error:
            _map_provider_error(error)
        text = getattr(interaction, "output_text", None) or ""
        return text.strip()


class AnthropicTransport:
    """messages.parse with Pydantic output_format; never sends temperature/top_p/top_k."""

    def __init__(self, *, api_key: str, model: str, timeout: float) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.model = model

    def complete(self, *, system: str, user: str) -> dict[str, Any]:
        import anthropic

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=LlmAnalysis,
                output_config={"effort": "low"},
            )
        except anthropic.APITimeoutError as error:
            raise ApiError(ErrorCode.TIMEOUT) from error
        except anthropic.APIStatusError as error:
            if error.status_code in {408, 504}:
                raise ApiError(ErrorCode.TIMEOUT) from error
            raise ApiError(ErrorCode.AI_UNAVAILABLE) from error
        except Exception as error:
            _map_provider_error(error)
        parsed = response.parsed_output
        if parsed is None:
            raise ApiError(ErrorCode.AI_INVALID_RESPONSE)
        data: dict[str, Any] = json.loads(parsed.model_dump_json(by_alias=True))
        return data

    def transcribe(self, image: Image.Image) -> str:
        import anthropic

        payload = _image_b64(image)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": payload,
                                },
                            },
                            {"type": "text", "text": VISION_PROMPT},
                        ],
                    }
                ],
                output_config={"effort": "low"},
            )
        except anthropic.APITimeoutError as error:
            raise ApiError(ErrorCode.TIMEOUT) from error
        except anthropic.APIStatusError as error:
            if error.status_code in {408, 504}:
                raise ApiError(ErrorCode.TIMEOUT) from error
            raise ApiError(ErrorCode.AI_UNAVAILABLE) from error
        except Exception as error:
            _map_provider_error(error)
        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts).strip()


class MockTransport:
    """Injectable transport for tests (no network)."""

    def __init__(
        self,
        complete_fn: Callable[[str, str], dict[str, Any]],
        transcribe_fn: Callable[[Image.Image], str] | None = None,
    ) -> None:
        self._complete = complete_fn
        self._transcribe = transcribe_fn or (lambda _image: "")

    def complete(self, *, system: str, user: str) -> dict[str, Any]:
        return self._complete(system, user)

    def transcribe(self, image: Image.Image) -> str:
        return self._transcribe(image)


def analyze_with_llm(transport: LlmTransport, *, system: str, user: str) -> dict[str, Any]:
    return transport.complete(system=system, user=user)


def make_vision_fallback(transport: LlmTransport) -> Callable[[Image.Image], Any]:
    from app.ocr import OcrResult

    def vision(image: Image.Image) -> OcrResult | None:
        try:
            text = transport.transcribe(image)
        except ApiError:
            logger.info("vision fallback failed")
            return None
        if not text.strip():
            return None
        return OcrResult(text=text, confidence=100.0, method="vision")

    return vision


def _image_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _map_provider_error(error: Exception) -> NoReturn:
    name = type(error).__name__.lower()
    message = str(error).lower()
    if "timeout" in name or "timeout" in message or "timed out" in message:
        raise ApiError(ErrorCode.TIMEOUT) from error
    if "429" in message or "rate" in message:
        raise ApiError(ErrorCode.AI_UNAVAILABLE) from error
    logger.error("llm provider error: %s", type(error).__name__)
    raise ApiError(ErrorCode.AI_UNAVAILABLE) from error
