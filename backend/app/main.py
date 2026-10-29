"""FastAPI app: routes, error envelope, CORS, request size guard, rate limits."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.analysis import analyze_extraction
from app.cache import TtlCache
from app.config import Settings, get_settings
from app.errors import ApiError, ErrorCode
from app.extraction import Extraction, extract_pdf
from app.llm import OpenRouter, create_llm
from app.ratelimit import DailyCounter, SlidingWindowLimiter, client_ip
from app.schema import AnalysisResult, AnalyzeRequest, ExtractResponse
from app.upload import read_pdf_upload

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pdf_insight")

# Room for the multipart framing around the file in the Content-Length check.
MULTIPART_OVERHEAD = 64 * 1024
# OCR is CPU-heavy; more parallel extractions only slow each other down.
EXTRACT_CONCURRENCY = 2
FILE_NAME_MAX = 255


def create_app(settings: Settings, llm: OpenRouter | None = None) -> FastAPI:
    app = FastAPI(title="PDF Insight API", docs_url=None, redoc_url=None, openapi_url=None)
    llm = llm or create_llm(settings)
    cache: TtlCache[Extraction] = TtlCache(ttl=settings.extraction_ttl_seconds)
    limiter = SlidingWindowLimiter(limit=settings.rate_limit_per_minute)
    daily = DailyCounter(limit=settings.daily_analysis_limit)
    extract_slots = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    app.state.cache = cache

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(ApiError(ErrorCode.INVALID_REQUEST))

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if error.status_code == 404 else ErrorCode.INVALID_REQUEST
        return error_response(ApiError(code))

    # Added before CORS, so CORS wraps it and 413/500 responses still carry CORS headers:
    # the browser can then show the Polish message instead of a network error.
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST" and (error := _body_size_error(request, settings)):
            return error_response(error)
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

    def check_rate_limit(request: Request) -> None:
        if retry_after := limiter.hit(client_ip(request)):
            raise ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/extract")
    async def extract(request: Request, file: Annotated[UploadFile, File()]) -> ExtractResponse:
        check_rate_limit(request)
        data = await read_pdf_upload(file, settings)
        file_name = (file.filename or "document.pdf")[:FILE_NAME_MAX]
        vision = llm if settings.vision_fallback else None
        # The deadline is checked between pages inside the worker thread, so the slot is held
        # until the work really stops (a cancelled await would leave the thread running).
        deadline = time.monotonic() + settings.extract_timeout_seconds
        async with extract_slots:
            extraction = await asyncio.to_thread(
                extract_pdf, data, file_name, settings, vision=vision, deadline=deadline
            )
        extraction_id = str(uuid.uuid4())
        cache.set(extraction_id, extraction)
        return ExtractResponse(
            extraction_id=extraction_id,
            file_name=file_name,
            pages=len(extraction.page_info),
            chars=sum(info.chars for info in extraction.page_info),
            page_info=extraction.page_info,
            warnings=extraction.warnings,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.extraction_ttl_seconds),
        )

    @app.post("/api/analyze")
    async def analyze(request: Request, body: AnalyzeRequest) -> AnalysisResult:
        check_rate_limit(request)
        extraction = cache.get(body.extraction_id)
        if extraction is None:
            raise ApiError(ErrorCode.EXTRACTION_NOT_FOUND)
        if llm is None:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        if not daily.hit():
            raise ApiError(ErrorCode.DAILY_LIMIT)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_extraction, llm, extraction, settings),
                timeout=settings.analyze_timeout_seconds,
            )
        except TimeoutError as error:
            raise ApiError(ErrorCode.TIMEOUT) from error

    return app


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=error.headers,
    )


def _body_size_error(request: Request, settings: Settings) -> ApiError | None:
    """POST bodies must declare their size, so the server never reads past the limit."""
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        return ApiError(ErrorCode.INVALID_REQUEST)
    if int(length) > settings.max_file_bytes + MULTIPART_OVERHEAD:
        return ApiError(ErrorCode.FILE_TOO_LARGE, max_mb=settings.max_file_mb)
    return None


app = create_app(get_settings())
