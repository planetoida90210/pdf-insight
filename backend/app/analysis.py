"""Analyze extracted text: LLM call, validate+retry, chunking, ground, assemble."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.chunking import merge_chunk_analyses, run_bounded, split_into_chunks
from app.errors import ApiError, ErrorCode
from app.grounding import ground_analysis
from app.llm import LlmTransport, analyze_with_llm
from app.prompts import SYSTEM_PROMPT, document_id, reduce_prompt, retry_prompt, user_prompt
from app.schema import (
    AnalysisResult,
    AnalysisWarning,
    DocumentInfo,
    LlmAnalysis,
    Meta,
    PageInfo,
)
from app.validation import parse_and_validate

logger = logging.getLogger("pdf_insight")


def analyze_extraction(
    *,
    transport: LlmTransport,
    provider: str,
    model: str,
    file_name: str,
    pages: int,
    text: str,
    page_info: list[PageInfo],
    extract_warnings: list[AnalysisWarning],
    chunk_chars: int = 40_000,
    chunk_concurrency: int = 3,
) -> AnalysisResult:
    started = time.perf_counter()
    chunks = split_into_chunks(text, chunk_chars)
    chunk_count = max(1, len(chunks))
    extra_warnings: list[AnalysisWarning] = []

    if chunk_count == 1:
        llm = _call_with_retry(transport, chunks[0] if chunks else text)
    else:
        logger.info(
            "analyze chunking chars=%s chunks=%s concurrency=%s",
            len(text),
            chunk_count,
            chunk_concurrency,
        )
        per_chunk = run_bounded(
            chunks,
            lambda chunk: _call_with_retry(transport, chunk),
            concurrency=chunk_concurrency,
        )
        merged = merge_chunk_analyses(per_chunk)
        reduced = _reduce_summary(transport, per_chunk)
        llm = LlmAnalysis(
            document=merged.document,
            summary=reduced.summary,
            key_points=reduced.key_points,
            entities=merged.entities,
            amounts=merged.amounts,
            dates=merged.dates,
            keywords=merged.keywords,
            suspicious_instructions=merged.suspicious_instructions,
        )
        extra_warnings.append(
            AnalysisWarning(
                code="CHUNKED",
                page=None,
                message=(
                    f"Dokument był zbyt długi — przeanalizowano go w {chunk_count} "
                    "częściach i scalono wyniki."
                ),
            )
        )

    grounded, ground_warnings = ground_analysis(llm, text)
    warnings = _merge_warnings(extract_warnings, grounded, ground_warnings)
    warnings.extend(extra_warnings)
    ocr_pages = sorted({p.page for p in page_info if p.method in {"ocr", "vision"}})
    hidden_pages = sorted(
        {w.page for w in extract_warnings if w.code == "HIDDEN_TEXT" and w.page is not None}
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result = AnalysisResult(
        document=DocumentInfo(
            file_name=file_name,
            pages=pages,
            language=grounded.document.language,
            type=grounded.document.type,
            title=grounded.document.title,
            date=grounded.document.date,
        ),
        summary=grounded.summary,
        key_points=grounded.key_points,
        entities=grounded.entities,
        amounts=grounded.amounts,
        dates=grounded.dates,
        keywords=grounded.keywords,
        warnings=warnings,
        meta=Meta(
            schema_version="1.0",
            analyzed_at=datetime.now(UTC),
            provider=provider,
            model=model,
            ocr_pages=ocr_pages,
            hidden_text_pages=hidden_pages,
            chunks=chunk_count,
            processing_ms=elapsed_ms,
        ),
    )
    logger.info(
        "analyze provider=%s model=%s pages=%s chunks=%s ms=%s warnings=%s",
        provider,
        model,
        pages,
        chunk_count,
        elapsed_ms,
        [w.code for w in warnings],
    )
    return result


def _call_with_retry(transport: LlmTransport, text: str) -> LlmAnalysis:
    doc_id = document_id()
    first_user = user_prompt(text, doc_id=doc_id)
    raw = analyze_with_llm(transport, system=SYSTEM_PROMPT, user=first_user)
    analysis, errors = parse_and_validate(raw)
    if analysis is not None:
        return analysis

    second_user = retry_prompt(text, errors, doc_id=doc_id)
    raw_retry = analyze_with_llm(transport, system=SYSTEM_PROMPT, user=second_user)
    analysis_retry, errors_retry = parse_and_validate(raw_retry)
    if analysis_retry is not None:
        return analysis_retry
    logger.info("ai invalid after retry codes=%s", len(errors_retry))
    raise ApiError(ErrorCode.AI_INVALID_RESPONSE)


def _reduce_summary(transport: LlmTransport, parts: list[LlmAnalysis]) -> LlmAnalysis:
    briefs = [(part.summary, list(part.key_points)) for part in parts]
    raw = analyze_with_llm(transport, system=SYSTEM_PROMPT, user=reduce_prompt(briefs))
    # Reuse document fields from the first chunk so validation can pass; only
    # summary/keyPoints from the reduce response are kept by the caller.
    seed = parts[0].model_dump(by_alias=True)
    if isinstance(raw, dict):
        if "summary" in raw:
            seed["summary"] = raw["summary"]
        if "keyPoints" in raw:
            seed["keyPoints"] = raw["keyPoints"]
        elif "key_points" in raw:
            seed["keyPoints"] = raw["key_points"]
    analysis, errors = parse_and_validate(seed)
    if analysis is not None:
        return analysis
    logger.info("ai reduce invalid codes=%s", len(errors))
    raise ApiError(ErrorCode.AI_INVALID_RESPONSE)


def _merge_warnings(
    extract_warnings: list[AnalysisWarning],
    grounded: LlmAnalysis,
    ground_warnings: list[AnalysisWarning],
) -> list[AnalysisWarning]:
    warnings = list(extract_warnings)
    warnings.extend(ground_warnings)
    for instruction in grounded.suspicious_instructions:
        warnings.append(
            AnalysisWarning(
                code="INJECTION_SUSPECTED",
                page=None,
                message=f"Model zgłosił podejrzaną instrukcję w dokumencie: „{instruction[:160]}”.",
            )
        )
    return warnings
