import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.main import create_app

ORIGIN = "https://planetoida90210.github.io"


@pytest.fixture
def app() -> FastAPI:
    app = create_app(Settings(allowed_origins=f"{ORIGIN},http://localhost:5173", max_file_mb=1))

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("secret document text")

    @app.get("/api/limited")
    async def limited() -> None:
        raise ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"})

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "gemini"}


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_api_error_keeps_headers(client: TestClient) -> None:
    response = client.get("/api/limited", headers={"Origin": ORIGIN})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.json()["error"]["message"].startswith("Zbyt wiele")


def test_unhandled_error_hides_details(client: TestClient) -> None:
    response = client.get("/api/boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.json()["error"]["code"] == "INTERNAL"
    assert "secret" not in response.text


def test_oversized_body_rejected_before_parsing(client: TestClient) -> None:
    response = client.post(
        "/api/health", content=b"0" * (2 * 1024 * 1024), headers={"Origin": ORIGIN}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_rejects_other_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
