"""Long documents (F-08): split on page boundaries, merge the per-chunk analyses."""

from collections import Counter
from collections.abc import Callable, Hashable, Iterable

from app.schema import Entities, LlmAnalysis, LlmDocument
from app.validation import dedupe

PAGE_SEPARATOR = "\n\n"


def split_into_chunks(pages: list[str], max_chars: int) -> list[str]:
    """Packs whole pages into chunks of at most `max_chars`; a longer page is a chunk of its own."""
    chunks: list[str] = []
    for page in pages:
        if chunks and len(chunks[-1]) + len(PAGE_SEPARATOR) + len(page) <= max_chars:
            chunks[-1] += PAGE_SEPARATOR + page
        else:
            chunks.append(page)
    return chunks


def merge_analyses(parts: list[LlmAnalysis]) -> LlmAnalysis:
    """Unions the lists (first occurrence wins); summary and keyPoints come from a later call."""
    documents = [part.document for part in parts]
    return parts[0].model_copy(
        update={
            "document": LlmDocument(
                language=_most_common(document.language for document in documents),
                type=_most_common(document.type for document in documents),
                title=next((d.title for d in documents if d.title), None),
                date=next((d.date for d in documents if d.date), None),
            ),
            "entities": Entities(
                organizations=dedupe(o for part in parts for o in part.entities.organizations),
                people=dedupe(p for part in parts for p in part.entities.people),
            ),
            "amounts": _unique_by(
                (a for part in parts for a in part.amounts), lambda a: (a.value, a.currency)
            ),
            "dates": _unique_by((d for part in parts for d in part.dates), lambda d: d.date),
            "keywords": dedupe(k for part in parts for k in part.keywords),
            "suspicious_instructions": dedupe(
                s for part in parts for s in part.suspicious_instructions
            ),
        }
    )


def _most_common[T](values: Iterable[T]) -> T:
    return Counter(values).most_common(1)[0][0]


def _unique_by[T](items: Iterable[T], key: Callable[[T], Hashable]) -> list[T]:
    first: dict[Hashable, T] = {}
    for item in items:
        first.setdefault(key(item), item)
    return list(first.values())
