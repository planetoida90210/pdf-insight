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


def test_health_answers_ok(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Nie znaleziono zasobu."}}


def test_invalid_body_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/api/analyze", json={"wrong": 1})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_api_error_keeps_headers_and_cors(client: TestClient) -> None:
    response = client.get("/api/limited", headers={"Origin": ORIGIN})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.json()["error"]["message"] == "Zbyt wiele żądań. Spróbuj ponownie za chwilę."


def test_unhandled_error_hides_details(client: TestClient) -> None:
    response = client.get("/api/boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.json()["error"]["code"] == "INTERNAL"
    assert "secret" not in response.text


def test_oversized_body_rejected_before_parsing(client: TestClient) -> None:
    response = client.post(
        "/api/extract", content=b"0" * (2 * 1024 * 1024), headers={"Origin": ORIGIN}
    )
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Plik jest za duży. Maksymalny rozmiar to 1 MB."
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_body_without_declared_length_is_rejected(client: TestClient) -> None:
    response = client.post("/api/extract", content=iter([b"%PDF-1.7"]))
    assert "content-length" not in response.request.headers
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


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
