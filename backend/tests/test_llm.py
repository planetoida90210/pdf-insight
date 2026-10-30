import base64
import json
import logging
from typing import Any

import httpx2
import pytest

from app.analysis import analyze_extraction
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.llm import MAX_TOKENS, OpenRouter, create_llm
from tests.fakes import budget, completion, extraction

KEY = "sk-or-test"
SCHEMA = {"type": "object"}


def openrouter(*replies: httpx2.Response | Exception) -> tuple[OpenRouter, list[httpx2.Request]]:
    """The client built by create_llm; its requests are recorded and get `replies` in turn."""
    requests: list[httpx2.Request] = []
    pending = iter(replies)

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        answer = next(pending)
        if isinstance(answer, Exception):
            raise answer
        return answer

    llm = create_llm(Settings(openrouter_api_key=KEY), budget(), httpx2.MockTransport(reply))
    assert llm is not None
    return llm, requests


def sent(request: httpx2.Request) -> Any:
    return json.loads(request.content)


def failure(code: int, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "metadata": {"error_type": "test"}}}


def test_analysis_request_asks_for_strict_json_without_sampling_parameters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm, requests = openrouter(httpx2.Response(200, json=completion('{"ok": true}')))
    with caplog.at_level(logging.INFO):
        answer = llm.generate(system="System.", prompt="Tajny tekst umowy.", json_schema=SCHEMA)

    assert answer == '{"ok": true}'
    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert sent(request) == {
        "model": "anthropic/claude-haiku-5.5",
        "messages": [
            {"role": "system", "content": "System."},
            {"role": "user", "content": [{"type": "text", "text": "Tajny tekst umowy."}]},
        ],
        "max_tokens": MAX_TOKENS,
        "reasoning": {"effort": "low", "exclude": True},
        "provider": {"require_parameters": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "analysis", "strict": True, "schema": SCHEMA},
        },
    }
    assert "Tajny" not in caplog.text


def test_vision_request_sends_the_image_after_the_text() -> None:
    llm, requests = openrouter(httpx2.Response(200, json=completion("Aneks nr 1")))
    assert llm.generate(system="System.", prompt="Przepisz.", image_png=b"png") == "Aneks nr 1"
    body = sent(requests[0])
    assert body["messages"][1]["content"] == [
        {"type": "text", "text": "Przepisz."},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"png").decode()},
        },
    ]
    assert "response_format" not in body


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        pytest.param(
            httpx2.Response(401, json=failure(401, "No auth credentials found")),
            ErrorCode.AI_UNAVAILABLE,
            id="401-invalid-key",
        ),
        pytest.param(
            httpx2.Response(402, json=failure(402, "Insufficient credits")),
            ErrorCode.AI_UNAVAILABLE,
            id="402-no-credits",
        ),
        pytest.param(
            httpx2.Response(429, json=failure(429, "Rate limit exceeded")),
            ErrorCode.AI_UNAVAILABLE,
            id="429-rate-limited",
        ),
        pytest.param(
            httpx2.Response(502, json=failure(502, "Provider returned error")),
            ErrorCode.AI_UNAVAILABLE,
            id="502-provider-error",
        ),
        pytest.param(
            httpx2.Response(500, json={}), ErrorCode.AI_UNAVAILABLE, id="500-no-error-body"
        ),
        pytest.param(
            httpx2.Response(200, json=failure(502, "Provider disconnected")),
            ErrorCode.AI_UNAVAILABLE,
            id="error-body-with-200",
        ),
        pytest.param(
            httpx2.Response(200, json=failure(408, "Upstream timed out")),
            ErrorCode.TIMEOUT,
            id="408-in-error-body",
        ),
        pytest.param(
            httpx2.Response(502, text="<html>Bad Gateway</html>"),
            ErrorCode.AI_UNAVAILABLE,
            id="non-json-body",
        ),
        pytest.param(
            httpx2.Response(200, json=[completion("{}")]),
            ErrorCode.AI_UNAVAILABLE,
            id="json-array-body",
        ),
        pytest.param(
            httpx2.Response(502, json={"error": "Bad gateway"}),
            ErrorCode.AI_UNAVAILABLE,
            id="error-as-text",
        ),
        pytest.param(httpx2.ReadTimeout("timed out"), ErrorCode.TIMEOUT, id="read-timeout"),
        pytest.param(httpx2.ConnectError("refused"), ErrorCode.AI_UNAVAILABLE, id="connect-error"),
    ],
)
def test_provider_failures_map_to_api_errors(
    reply: httpx2.Response | Exception, code: ErrorCode
) -> None:
    llm, _ = openrouter(reply)
    with pytest.raises(ApiError) as raised:
        llm.generate(system="System.", prompt="Tekst.")
    assert raised.value.code == code


@pytest.mark.parametrize(
    "body",
    [
        completion(None),
        completion(""),
        completion("not json"),
        {"id": "gen-test", "choices": []},
        {"choices": [{"message": {"content": [{"type": "text", "text": "{}"}]}}]},
    ],
    ids=["null", "empty", "not-json", "no-choices", "content-parts"],
)
def test_unusable_answer_is_retried_once_then_rejected(body: dict[str, Any]) -> None:
    llm, requests = openrouter(*(httpx2.Response(200, json=body) for _ in range(2)))
    with pytest.raises(ApiError) as raised:
        analyze_extraction(llm, extraction(), Settings())
    assert raised.value.code == ErrorCode.AI_INVALID_RESPONSE
    assert len(requests) == 2


def test_client_without_a_budget_makes_no_call() -> None:
    def refuse(_: httpx2.Request) -> httpx2.Response:
        raise AssertionError("request sent without a budget")

    llm = create_llm(Settings(openrouter_api_key=KEY), transport=httpx2.MockTransport(refuse))
    assert llm is not None
    with pytest.raises(ApiError) as raised:
        llm.generate(system="System.", prompt="Tekst.")
    assert raised.value.code == ErrorCode.DAILY_LIMIT
