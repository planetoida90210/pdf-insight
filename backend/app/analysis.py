"""Analysis pipeline: LLM call with one validated retry, chunk merge, grounding, result assembly."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.chunking import merge_analyses, split_into_chunks
from app.config import Settings
from app.errors import ApiError, ErrorCode, WarningCode, warning
from app.extraction import Extraction
from app.grounding import ground_analysis
from app.llm import PROVIDER, OpenRouter
from app.prompts import (
    ANALYZE_TASK,
    REDUCE_TASK,
    SYSTEM_PROMPT,
    document_prompt,
    parts_digest,
    retry_note,
)
from app.schema import LLM_JSON_SCHEMA, AnalysisResult, DocumentInfo, LlmAnalysis, Meta
from app.validation import parse_analysis

logger = logging.getLogger("pdf_insight")

# The brief allows one retry after an invalid AI response.
ATTEMPTS = 2
CHUNK_CONCURRENCY = 3


def analyze_extraction(
    llm: OpenRouter, extraction: Extraction, settings: Settings
) -> AnalysisResult:
    started = time.perf_counter()
    chunks = split_into_chunks(extraction.pages, settings.chunk_chars)
    analysis, removed = ground_analysis(_analyze_chunks(llm, chunks), extraction.text)

    warnings = list(extraction.warnings)
    if removed:
        warnings.append(warning(WarningCode.UNGROUNDED_REMOVED, count=removed))
    if len(chunks) > 1:
        warnings.append(warning(WarningCode.CHUNKED, chunks=len(chunks)))
    warnings += [
        warning(WarningCode.INJECTION_SUSPECTED, snippet=quote)
        for quote in analysis.suspicious_instructions
    ]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "analyzed chunks=%s ms=%s warnings=%s", len(chunks), elapsed_ms, [w.code for w in warnings]
    )
    return AnalysisResult(
        document=DocumentInfo(
            file_name=extraction.file_name,
            pages=len(extraction.page_info),
            **analysis.document.model_dump(),
        ),
        summary=analysis.summary,
        key_points=analysis.key_points,
        entities=analysis.entities,
        amounts=analysis.amounts,
        dates=analysis.dates,
        keywords=analysis.keywords,
        warnings=warnings,
        meta=Meta(
            schema_version="1.0",
            analyzed_at=datetime.now(UTC),
            provider=PROVIDER,
            model=settings.llm_model,
            ocr_pages=[info.page for info in extraction.page_info if info.method != "text"],
            hidden_text_pages=[
                w.page for w in extraction.warnings if w.code == WarningCode.HIDDEN_TEXT and w.page
            ],
            chunks=len(chunks),
            processing_ms=elapsed_ms,
        ),
    )


def _analyze_chunks(llm: OpenRouter, chunks: list[str]) -> LlmAnalysis:
    """One chunk: one analysis. More: analyse each, merge them, then summarise the summaries."""
    if len(chunks) == 1:
        return _ask(llm, ANALYZE_TASK, chunks[0])
    with ThreadPoolExecutor(CHUNK_CONCURRENCY) as pool:
        parts = list(pool.map(lambda chunk: _ask(llm, ANALYZE_TASK, chunk), chunks))
    overview = _ask(llm, REDUCE_TASK, parts_digest(parts))
    return merge_analyses(parts).model_copy(
        update={"summary": overview.summary, "key_points": overview.key_points}
    )


def _ask(llm: OpenRouter, task: str, document: str) -> LlmAnalysis:
    prompt = document_prompt(task, document)
    errors: list[str] = []
    for _ in range(ATTEMPTS):
        raw = llm.generate(
            system=SYSTEM_PROMPT, prompt=prompt + retry_note(errors), json_schema=LLM_JSON_SCHEMA
        )
        analysis, errors = parse_analysis(raw)
        if analysis is not None:
            return analysis
    logger.warning("invalid AI response after retry: %s", errors)
    raise ApiError(ErrorCode.AI_INVALID_RESPONSE)
