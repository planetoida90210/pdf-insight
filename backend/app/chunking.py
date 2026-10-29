"""Split long documents on page boundaries, merge per-chunk analyses (F-08)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast

from app.errors import ApiError
from app.schema import Amount, DateEntry, DocumentType, Entities, LlmAnalysis, LlmDocument

PAGE_BLOCK_RE = re.compile(
    r"\[Strona\s+(\d+)\]\n?(.*?)(?=\n\n\[Strona\s+\d+\]|\Z)",
    re.DOTALL,
)


def split_into_chunks(text: str, chunk_chars: int) -> list[str]:
    """Pack page blocks into chunks of at most `chunk_chars` (one oversize page alone)."""
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be >= 1")
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= chunk_chars:
        return [stripped]

    pages = _page_blocks(stripped)
    if not pages:
        return [stripped[i : i + chunk_chars] for i in range(0, len(stripped), chunk_chars)]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in pages:
        block_len = len(block)
        sep = 2 if current else 0  # "\n\n" between blocks
        if current and current_len + sep + block_len > chunk_chars:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += sep + block_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def merge_chunk_analyses(parts: list[LlmAnalysis]) -> LlmAnalysis:
    """Dedupe entities/keywords/amounts/dates; document fields from first non-null / majority."""
    if not parts:
        raise ValueError("merge requires at least one chunk analysis")
    if len(parts) == 1:
        return parts[0]

    orgs = _dedupe_ci(name for part in parts for name in part.entities.organizations)
    people = _dedupe_ci(name for part in parts for name in part.entities.people)
    keywords = _dedupe_ci(word for part in parts for word in part.keywords)

    amounts: list[Amount] = []
    seen_amounts: set[tuple[float, str]] = set()
    for part in parts:
        for amount in part.amounts:
            key = (amount.value, amount.currency)
            if key in seen_amounts:
                continue
            seen_amounts.add(key)
            amounts.append(amount)

    dates: list[DateEntry] = []
    seen_dates: set[str] = set()
    for part in parts:
        for entry in part.dates:
            if entry.date in seen_dates:
                continue
            seen_dates.add(entry.date)
            dates.append(entry)

    suspicious = _dedupe_ci(item for part in parts for item in part.suspicious_instructions)

    languages = [part.document.language for part in parts if part.document.language]
    types = [part.document.type for part in parts if part.document.type]
    language = _majority(languages) or parts[0].document.language
    majority_type = _majority(types)
    doc_type: DocumentType = (
        cast(DocumentType, majority_type) if majority_type else parts[0].document.type
    )
    title = next((part.document.title for part in parts if part.document.title), None)
    doc_date = next((part.document.date for part in parts if part.document.date), None)

    # Placeholder summary/keyPoints — replaced by the reduce call.
    return LlmAnalysis(
        document=LlmDocument(language=language, type=doc_type, title=title, date=doc_date),
        summary=parts[0].summary,
        key_points=list(parts[0].key_points),
        entities=Entities(organizations=orgs, people=people),
        amounts=amounts,
        dates=dates,
        keywords=keywords,
        suspicious_instructions=suspicious,
    )


def run_bounded[T](
    items: list[T],
    worker: Callable[[T], LlmAnalysis],
    *,
    concurrency: int,
) -> list[LlmAnalysis]:
    """Run `worker` over items with bounded concurrency; first ApiError fails the batch."""
    if not items:
        return []
    workers = max(1, concurrency)
    if len(items) == 1 or workers == 1:
        return [worker(item) for item in items]

    results: list[LlmAnalysis | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = {pool.submit(worker, item): index for index, item in enumerate(items)}
        try:
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
        except ApiError:
            for future in futures:
                future.cancel()
            raise
    return [result for result in results if result is not None]


def _page_blocks(text: str) -> list[str]:
    matches = list(PAGE_BLOCK_RE.finditer(text))
    if not matches:
        return []
    blocks: list[str] = []
    for match in matches:
        page_no = match.group(1)
        body = match.group(2).rstrip()
        blocks.append(f"[Strona {page_no}]\n{body}".rstrip())
    return blocks


def _dedupe_ci(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _majority(values: Sequence[str]) -> str | None:
    if not values:
        return None
    counts = Counter(values)
    return counts.most_common(1)[0][0]
