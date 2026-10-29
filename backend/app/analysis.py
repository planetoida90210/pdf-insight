"""Analyze extracted text: LLM call, validate+retry, ground, assemble AnalysisResult."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.errors import ApiError, ErrorCode
from app.grounding import ground_analysis
from app.llm import LlmTransport, analyze_with_llm
from app.prompts import SYSTEM_PROMPT, document_id, retry_prompt, user_prompt
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
) -> AnalysisResult:
    started = time.perf_counter()
    doc_id = document_id()
    llm = _call_with_retry(transport, text, doc_id)
    grounded, ground_warnings = ground_analysis(llm, text)
    warnings = _merge_warnings(extract_warnings, grounded, ground_warnings)
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
            chunks=1,
            processing_ms=elapsed_ms,
        ),
    )
    logger.info(
        "analyze provider=%s model=%s pages=%s ms=%s warnings=%s",
        provider,
        model,
        pages,
        elapsed_ms,
        len(warnings),
    )
    return result


def _call_with_retry(transport: LlmTransport, text: str, doc_id: str) -> LlmAnalysis:
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
    logger.info("ai invalid after retry: %s", errors_retry[:3])
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
