import json
from collections.abc import Callable
from typing import Any

import httpx2

from app.extraction import Extraction
from app.llm import OpenRouter
from app.schema import AnalysisWarning, PageInfo


def llm_answer(**overrides: Any) -> str:
    """A valid model answer as JSON text; keyword arguments replace top-level fields."""
    answer: dict[str, Any] = {
        "document": {"language": "pl", "type": "umowa", "title": "Umowa", "date": "2026-03-12"},
        "summary": "Umowa dotyczy wdrożenia CRM. Obowiązuje od kwietnia. Wynagrodzenie jest stałe.",
        "keyPoints": ["Punkt A", "Punkt B", "Punkt C"],
        "entities": {"organizations": ["Acme"], "people": ["Anna Kowalczyk"]},
        "amounts": [{"value": 100000, "currency": "PLN", "context": "wynagrodzenie"}],
        "dates": [{"date": "2026-03-12", "context": "podpisanie"}],
        "keywords": ["CRM"],
        "suspiciousInstructions": [],
    }
    return json.dumps(answer | overrides, ensure_ascii=False)


class FakeLlm(OpenRouter):
    """Answers every call with `respond(prompt)` instead of the network and records the prompts."""

    def __init__(self, respond: Callable[[str], str]) -> None:
        super().__init__(httpx2.Client(), "test/model")
        self.respond = respond
        self.prompts: list[str] = []

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        image_png: bytes | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        return self.respond(prompt)


def extraction(
    text: str = "Umowa z dnia 12.03.2026. Wynagrodzenie 100 000 PLN.",
    *,
    page_info: list[PageInfo] | None = None,
    warnings: list[AnalysisWarning] | None = None,
) -> Extraction:
    return Extraction(
        file_name="umowa.pdf",
        pages=[f"[Strona 1]\n{text}"],
        page_info=page_info or [PageInfo(page=1, method="text", chars=len(text), confidence=None)],
        warnings=warnings or [],
    )
