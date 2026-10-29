import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.config import Settings, get_settings
from app.errors import ApiError, ErrorCode

logger = logging.getLogger("pdf_insight")

# Multipart framing around the file; anything bigger than file limit + this is rejected
# before the body is parsed.
MULTIPART_OVERHEAD = 64 * 1024


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=error.headers,
    )


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="PDF Insight API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(ApiError(ErrorCode.INVALID_REQUEST))

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, error: HTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if error.status_code == 404 else ErrorCode.INVALID_REQUEST
        return error_response(ApiError(code))

    # Registered before CORS so CORS wraps it: even 413/500 responses carry CORS headers
    # and the browser can show the Polish message instead of a generic network error.
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if (
            length
            and length.isdigit()
            and int(length) > settings.max_file_bytes + MULTIPART_OVERHEAD
        ):
            return error_response(
                ApiError(
                    ErrorCode.FILE_TOO_LARGE,
                    f"Plik jest za duży. Maksymalny rozmiar to {settings.max_file_mb} MB.",
                )
            )
        try:
            return await call_next(request)
        except Exception as error:
            logger.error("unhandled %s on %s", type(error).__name__, request.url.path)
            return error_response(ApiError(ErrorCode.INTERNAL))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app(get_settings())
