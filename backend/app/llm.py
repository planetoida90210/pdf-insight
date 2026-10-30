"""OpenRouter chat completions: one call for analysis (JSON schema) and page OCR (image)."""

import base64
import logging
from typing import Any

import httpx2

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.ratelimit import Charge

logger = logging.getLogger(__name__)

PROVIDER = "openrouter"
BASE_URL = "https://openrouter.ai/api/v1"
# Room for the longest answer: the amounts and dates of a 150,000-character chunk, or a dense
# page transcribed. Reasoning tokens count towards this ceiling as well.
MAX_TOKENS = 16_000
TIMEOUT_STATUSES = {408, 504}


class ContentFilterError(ApiError):
    """The provider's content filter withheld the answer; another provider may give it."""

    def __init__(self, provider: str | None) -> None:
        super().__init__(ErrorCode.AI_INVALID_RESPONSE)
        self.provider = provider


class OpenRouter:
    def __init__(self, client: httpx2.Client, model: str, charge: Charge | None = None) -> None:
        self._client = client
        self.model = model
        self._charge = charge

    def billed_to(self, charge: Charge) -> "OpenRouter":
        """This client with its calls taken from the budget behind `charge`; the connection pool
        is shared."""
        return OpenRouter(self._client, self.model, charge)

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        image_png: bytes | None = None,
        json_schema: dict[str, Any] | None = None,
        timeout: float | None = None,
        avoid: str | None = None,
    ) -> str:
        """Returns the answer text; provider failures raise ApiError (AI_UNAVAILABLE or TIMEOUT)
        and a content filter's refusal raises ContentFilterError.

        Every call takes one unit of the budget; DAILY_LIMIT once it is used up, and always
        without one. `timeout` (seconds) replaces LLM_TIMEOUT_SECONDS for this call. `avoid` is
        a provider name, as OpenRouter reports it, not to route this call to.
        """
        if self._charge is None or not self._charge():
            logger.error("daily LLM call limit reached")
            raise ApiError(ErrorCode.DAILY_LIMIT)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_png is not None:
            url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": url}})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "max_tokens": MAX_TOKENS,
            "reasoning": {"effort": "low", "exclude": True},
            # Route only to provider endpoints that support every parameter sent here.
            "provider": {"require_parameters": True},
        }
        if avoid is not None:
            body["provider"]["ignore"] = [avoid]
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "analysis", "strict": True, "schema": json_schema},
            }
        return _answer_text(self._post(body, timeout))

    def _post(self, body: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        limit = httpx2.USE_CLIENT_DEFAULT if timeout is None else timeout
        try:
            response = self._client.post("/chat/completions", json=body, timeout=limit)
            data = response.json()
        except httpx2.TimeoutException as error:
            raise _provider_error(408, type(error).__name__) from error
        except (httpx2.HTTPError, ValueError) as error:
            raise _provider_error(502, type(error).__name__) from error
        if not isinstance(data, dict):
            raise _provider_error(response.status_code, "reply is not a JSON object")
        failure = data.get("error") or {}
        if not isinstance(failure, dict):
            failure = {"message": failure}
        # An upstream failure can also arrive in the body of an HTTP 200 response.
        if failure or not response.is_success:
            error_type = (failure.get("metadata") or {}).get("error_type")
            message = str(failure.get("message"))[:200]
            raise _provider_error(
                failure.get("code") or response.status_code, f"{error_type}: {message}"
            )
        return data


def create_llm(
    settings: Settings,
    charge: Charge | None = None,
    transport: httpx2.BaseTransport | None = None,
) -> OpenRouter | None:
    """None without an API key: extraction still works, analysis answers AI_UNAVAILABLE."""
    key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else ""
    if not key:
        logger.warning("OPENROUTER_API_KEY is not set: analysis and vision OCR are off")
        return None
    client = httpx2.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=settings.llm_timeout_seconds,
        transport=transport,
    )
    return OpenRouter(client, settings.llm_model, charge)


def _answer_text(data: dict[str, Any]) -> str:
    """The first choice's text; "" when there is none, which callers treat as unusable."""
    choice = (data.get("choices") or [{}])[0]
    usage = data.get("usage") or {}
    logger.info(
        "openrouter id=%s provider=%s finish=%s tokens=%s/%s",
        data.get("id"),
        data.get("provider"),
        choice.get("finish_reason"),
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    if choice.get("finish_reason") == "content_filter":
        provider = data.get("provider")
        raise ContentFilterError(provider if isinstance(provider, str) else None)
    content = (choice.get("message") or {}).get("content")
    return content if isinstance(content, str) else ""


def _provider_error(status: int, detail: str) -> ApiError:
    """Logs the status and error type, never document content, and maps them to an API code."""
    logger.warning("openrouter call failed status=%s %s", status, detail)
    return ApiError(ErrorCode.TIMEOUT if status in TIMEOUT_STATUSES else ErrorCode.AI_UNAVAILABLE)
