"""FastAPI app: routes, error envelope, CORS, request size guard, rate limits."""

import asyncio
import logging
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
from app.config import LOG_FORMAT, Settings, get_settings
from app.errors import ApiError, ErrorCode
from app.extraction import Extraction, read_pdf
from app.llm import OpenRouter, create_llm
from app.ratelimit import DailyCounter, SlidingWindowLimiter, client_ip
from app.schema import AnalysisResult, AnalyzeRequest, ExtractResponse
from app.upload import read_pdf_upload
from app.worker import run_isolated

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Room for the multipart framing around the file in the Content-Length check.
MULTIPART_OVERHEAD = 64 * 1024
# One extraction with OCR peaks near 300 MiB (parser process plus Tesseract), so a second one
# would not fit in a 512 MiB instance; on one shared vCPU it would not finish sooner either.
EXTRACT_CONCURRENCY = 1
FILE_NAME_MAX = 255
# The API answers JSON only: nothing in a response may be rendered, framed, sniffed or cached.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Strict-Transport-Security": "max-age=31536000",
}


def create_app(settings: Settings, llm: OpenRouter | None = None) -> FastAPI:
    app = FastAPI(title="PDF Insight API", docs_url=None, redoc_url=None, openapi_url=None)
    budget = DailyCounter(limit=settings.daily_llm_call_limit)
    llm = llm or create_llm(settings, budget)
    cache: TtlCache[Extraction] = TtlCache(ttl=settings.extraction_ttl_seconds)
    limiter = SlidingWindowLimiter(limit=settings.rate_limit_per_minute)
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

    # Added before CORS, so CORS wraps it and 413/429/500 responses still carry CORS headers:
    # the browser can then show the Polish message instead of a network error.
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await _guarded(request, call_next)
        response.headers.update(SECURITY_HEADERS)
        return response

    async def _guarded(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Both checks run before FastAPI reads the body, so a rejected upload is never parsed.
        if request.method == "POST":
            rejected = _body_size_error(request, settings) or _rate_limit_error(request, limiter)
            if rejected:
                return error_response(rejected)
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

    @app.post("/api/extract")
    async def extract(file: Annotated[UploadFile, File()]) -> ExtractResponse:
        file_name = (file.filename or "document.pdf")[:FILE_NAME_MAX]
        # Read inside the slot: queued uploads wait in Starlette's temporary files, not in RAM.
        async with extract_slots:
            data = await read_pdf_upload(file, settings)
            extraction = await asyncio.to_thread(
                run_isolated,
                read_pdf,
                data,
                file_name,
                settings,
                budget,
                timeout=settings.extract_timeout_seconds,
                memory_mb=settings.extract_memory_mb,
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
    async def analyze(body: AnalyzeRequest) -> AnalysisResult:
        extraction = cache.get(body.extraction_id)
        if extraction is None:
            raise ApiError(ErrorCode.EXTRACTION_NOT_FOUND)
        if llm is None:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(analyze_extraction, llm, extraction, settings),
                timeout=settings.analyze_timeout_seconds,
            )
        except TimeoutError as error:
            raise ApiError(ErrorCode.TIMEOUT) from error
        # One analysis per upload; after a failure the client may retry with the same id.
        cache.delete(body.extraction_id)
        return result

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


def _rate_limit_error(request: Request, limiter: SlidingWindowLimiter) -> ApiError | None:
    if retry_after := limiter.hit(client_ip(request)):
        return ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})
    return None


app = create_app(get_settings())
