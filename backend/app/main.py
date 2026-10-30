"""FastAPI app: routes, error envelope, CORS, request size guard, rate limits."""

import asyncio
import logging
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.analysis import analyze_extraction
from app.cache import TtlCache
from app.config import Settings, configure_logging, error_frames, get_settings
from app.errors import ApiError, ErrorCode
from app.extraction import Extraction, read_pdf
from app.llm import OpenRouter, create_llm
from app.ratelimit import DailyLlmLimits, SlidingWindowLimiter, client_ip
from app.schema import FILE_NAME_MAX, AnalysisResult, AnalyzeRequest, ExtractResponse
from app.upload import read_ocr_upload, read_pdf_upload
from app.worker import run_isolated

configure_logging()
logger = logging.getLogger(__name__)

# Room for the multipart framing around the parts in the Content-Length check.
MULTIPART_OVERHEAD = 64 * 1024
# On one shared vCPU a second extraction would not finish sooner, and each one with OCR peaks
# near 300 MiB (parser process plus Tesseract).
EXTRACT_CONCURRENCY = 1
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
    limits = DailyLlmLimits(settings.daily_llm_call_limit, settings.daily_llm_calls_per_ip)
    llm = llm or create_llm(settings)
    cache: TtlCache[Extraction] = TtlCache(ttl=settings.extraction_ttl_seconds)
    limiter = SlidingWindowLimiter(limit=settings.rate_limit_per_minute)
    extract_slots = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    analyzing: set[str] = set()
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
            name, path = type(error).__name__, request.url.path
            logger.error("unhandled %s on %s\n%s", name, path, error_frames(error))
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
    async def extract(
        request: Request,
        file: Annotated[UploadFile, File()],
        ocr: Annotated[UploadFile | None, File()] = None,
    ) -> ExtractResponse:
        file_name = _file_name(file.filename)
        # Read inside the slot: queued uploads wait in Starlette's temporary files, not in RAM.
        async with extract_slots:
            data = await read_pdf_upload(file, settings)
            ocr_pages = await read_ocr_upload(ocr, settings)
            vision_calls = limits.allowance(client_ip(request), settings.vision_max_pages)
            with vision_calls as allowance:
                extraction = await asyncio.to_thread(
                    run_isolated,
                    read_pdf,
                    data,
                    file_name,
                    settings,
                    allowance.hit,
                    ocr_pages,
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
    async def analyze(request: Request, body: AnalyzeRequest) -> AnalysisResult:
        extraction_id = body.extraction_id
        extraction = cache.get(extraction_id)
        # An id under analysis is taken: a parallel request for it would pay for a second one.
        if extraction is None or extraction_id in analyzing:
            raise ApiError(ErrorCode.EXTRACTION_NOT_FOUND)
        if llm is None:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        billed = llm.billed_to(partial(limits.hit, client_ip(request)))
        analyzing.add(extraction_id)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(analyze_extraction, billed, extraction, settings),
                timeout=settings.analyze_timeout_seconds,
            )
        except TimeoutError as error:
            raise ApiError(ErrorCode.TIMEOUT) from error
        finally:
            analyzing.discard(extraction_id)
        # One analysis per upload; after a failure the client may retry with the same id.
        cache.delete(extraction_id)
        return result

    return app


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=error.headers,
    )


def _file_name(name: str | None) -> str:
    """The client's file name without format characters, which change how it reads (U+202E
    shows "raport<U+202E>txt.pdf" as "raportfdp.txt"), cut to FILE_NAME_MAX UTF-16 code units;
    a surrogate pair cut in half is dropped."""
    visible = "".join(char for char in name or "" if unicodedata.category(char) != "Cf")
    cut = visible.encode("utf-16-le")[: 2 * FILE_NAME_MAX].decode("utf-16-le", "ignore")
    return cut or "document.pdf"


def _body_size_error(request: Request, settings: Settings) -> ApiError | None:
    """POST bodies must declare their size, so the server never reads past the limit."""
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        return ApiError(ErrorCode.INVALID_REQUEST)
    if int(length) > settings.max_file_bytes + settings.max_ocr_bytes + MULTIPART_OVERHEAD:
        return ApiError(ErrorCode.FILE_TOO_LARGE, max_mb=settings.max_file_mb)
    return None


def _rate_limit_error(request: Request, limiter: SlidingWindowLimiter) -> ApiError | None:
    if retry_after := limiter.hit(client_ip(request)):
        return ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})
    return None


app = create_app(get_settings())
