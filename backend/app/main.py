import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
from app.extraction import ExtractionResult, extract_pdf
from app.llm import LlmTransport, create_transport, make_vision_fallback
from app.ocr import VisionFallback
from app.ratelimit import DailyCounter, SlidingWindowLimiter, client_ip
from app.schema import AnalysisResult, AnalysisWarning, AnalyzeRequest, ExtractResponse, PageInfo
from app.upload import open_pdf, read_pdf_upload

logger = logging.getLogger("pdf_insight")

# Multipart framing around the file; anything bigger than file limit + this is rejected
# before the body is parsed.
MULTIPART_OVERHEAD = 64 * 1024
EXTRACT_CONCURRENCY = 2


@dataclass(slots=True)
class CachedExtraction:
    """Server-side payload keyed by extractionId; analyze consumes `text`."""

    file_name: str
    pages: int
    text: str
    chars: int
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning]
    expires_at: datetime


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=error.headers,
    )


def create_app(
    settings: Settings,
    *,
    llm_transport: LlmTransport | None = None,
    vision: VisionFallback | None = None,
) -> FastAPI:
    app = FastAPI(title="PDF Insight API", docs_url=None, redoc_url=None, openapi_url=None)
    cache: TtlCache[CachedExtraction] = TtlCache(ttl=float(settings.extraction_ttl_seconds))
    limiter = SlidingWindowLimiter(limit=settings.rate_limit_per_minute)
    daily = DailyCounter(limit=settings.daily_analysis_limit)
    extract_lock = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    app.state.settings = settings
    app.state.cache = cache
    app.state.limiter = limiter
    app.state.daily = daily
    app.state.llm_transport = llm_transport
    app.state.vision = vision

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

    def resolve_transport() -> LlmTransport:
        existing = app.state.llm_transport
        if existing is not None:
            return existing  # type: ignore[no-any-return]
        return create_transport(settings)

    def resolve_vision() -> VisionFallback | None:
        if app.state.vision is not None:
            return app.state.vision  # type: ignore[no-any-return]
        if not settings.vision_fallback:
            return None
        try:
            return make_vision_fallback(resolve_transport())
        except ApiError:
            # No API key yet — OCR still runs; vision stays a no-op.
            return None

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": settings.llm_provider}

    @app.post("/api/extract")
    async def extract(request: Request, file: Annotated[UploadFile, File()]) -> ExtractResponse:
        retry_after = limiter.hit(client_ip(request))
        if retry_after is not None:
            raise ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})

        data = await read_pdf_upload(file, settings.max_file_bytes)
        # Validate open/encryption/page count before the heavier extraction work.
        pdf = open_pdf(data, settings.max_pages)
        pdf.close()

        vision_fn = resolve_vision()

        async with extract_lock:
            result: ExtractionResult = await asyncio.to_thread(
                extract_pdf, data, settings, vision=vision_fn
            )

        extraction_id = str(uuid.uuid4())
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.extraction_ttl_seconds)
        file_name = file.filename or "document.pdf"
        cache.set(
            extraction_id,
            CachedExtraction(
                file_name=file_name,
                pages=result.pages,
                text=result.text,
                chars=result.chars,
                page_info=result.page_info,
                warnings=result.warnings,
                expires_at=expires_at,
            ),
        )
        logger.info(
            "extract id=%s pages=%s chars=%s file_bytes=%s",
            extraction_id,
            result.pages,
            result.chars,
            len(data),
        )
        return ExtractResponse(
            extraction_id=extraction_id,
            file_name=file_name,
            pages=result.pages,
            chars=result.chars,
            page_info=result.page_info,
            warnings=result.warnings,
            expires_at=expires_at,
        )

    @app.post("/api/analyze")
    async def analyze(request: Request, body: AnalyzeRequest) -> AnalysisResult:
        retry_after = limiter.hit(client_ip(request))
        if retry_after is not None:
            raise ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})
        if not daily.hit():
            raise ApiError(ErrorCode.DAILY_LIMIT)

        cached = cache.get(body.extraction_id)
        if cached is None:
            raise ApiError(ErrorCode.EXTRACTION_NOT_FOUND)

        transport = resolve_transport()
        model = settings.resolved_model
        return await asyncio.to_thread(
            analyze_extraction,
            transport=transport,
            provider=settings.llm_provider,
            model=model,
            file_name=cached.file_name,
            pages=cached.pages,
            text=cached.text,
            page_info=cached.page_info,
            extract_warnings=cached.warnings,
        )

    return app


app = create_app(get_settings())
