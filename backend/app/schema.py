"""API contract: the analysis result, the extract response and the model-facing subset."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
)
from pydantic.alias_generators import to_camel
from pydantic.json_schema import SkipJsonSchema

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "analysis.schema.json"


def _calendar_date(value: str) -> str:
    date.fromisoformat(value)
    return value


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# A plain string (not `date`) keeps the JSON shape identical to the Zod side and rejects
# timestamps or datetimes that pydantic's date type would coerce.
IsoDate = Annotated[
    str,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"format": "date"}),
    AfterValidator(_calendar_date),
]
PageNumber = Annotated[int, Field(ge=1)]
LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{2}$")]
# The browser's schema (Zod) counts UTF-16 code units, so the server cuts file names to this many.
FILE_NAME_MAX = 255
DocumentType = Literal["faktura", "umowa", "oferta", "raport", "inne"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        strict=True,
    )


class DocumentInfo(ApiModel):
    file_name: Annotated[str, StringConstraints(min_length=1, max_length=FILE_NAME_MAX)]
    pages: PageNumber
    language: LanguageCode
    type: DocumentType
    title: NonEmptyStr | None
    date: IsoDate | None


class Entities(ApiModel):
    organizations: list[NonEmptyStr]
    people: list[NonEmptyStr]


class Amount(ApiModel):
    value: Annotated[float, Field(allow_inf_nan=False)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    context: NonEmptyStr


class DateEntry(ApiModel):
    date: IsoDate
    context: NonEmptyStr


class AnalysisWarning(ApiModel):
    code: Annotated[str, Field(pattern=r"^[A-Z_]+$")]
    page: PageNumber | None
    message: NonEmptyStr
    # The document text the message quotes, to tell whether a later warning repeats it; never sent.
    snippet: SkipJsonSchema[str | None] = Field(default=None, exclude=True)


class Meta(ApiModel):
    schema_version: Literal["1.0"]
    analyzed_at: AwareDatetime
    provider: NonEmptyStr
    model: NonEmptyStr
    ocr_pages: list[PageNumber]
    hidden_text_pages: list[PageNumber]
    chunks: PageNumber
    processing_ms: Annotated[int, Field(ge=0)]


class AnalysisResult(ApiModel):
    document: DocumentInfo
    summary: NonEmptyStr
    key_points: Annotated[list[NonEmptyStr], Field(min_length=3, max_length=7)]
    entities: Entities
    amounts: list[Amount]
    dates: list[DateEntry]
    keywords: list[NonEmptyStr]
    warnings: list[AnalysisWarning]
    meta: Meta


class PageInfo(ApiModel):
    page: PageNumber
    method: Literal["text", "ocr", "vision"]
    chars: int
    confidence: float | None


class ExtractResponse(ApiModel):
    extraction_id: str
    file_name: str
    pages: PageNumber
    chars: int
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning]
    expires_at: AwareDatetime


# Far more than OCR reads from one page: a dense A4 page holds under 10,000 characters.
OCR_PAGE_MAX_CHARS = 100_000


class OcrPage(ApiModel):
    """A page the browser read with OCR: the optional `ocr` part of POST /api/extract."""

    page: PageNumber
    text: Annotated[str, StringConstraints(max_length=OCR_PAGE_MAX_CHARS)]
    confidence: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


OCR_PAGES = TypeAdapter(list[OcrPage])


class AnalyzeRequest(ApiModel):
    extraction_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


IN_DOCUMENT_LANGUAGE = "Written in the language of document.language."
# The codes are Polish words; the model must not take them for the language to write in.
DOCUMENT_TYPE_CODES = (
    "One of these fixed codes, whatever the document's language: faktura = any invoice or bill "
    "(also pro forma, credit note, receipt), umowa = contract or agreement (also its annex or "
    "terms), oferta = offer, quotation or price list, raport = report, statement or minutes, "
    "inne = anything else."
)


# The model fills only these fields; fileName, pages, warnings and meta come from the backend.
class LlmDocument(ApiModel):
    language: LanguageCode
    type: Annotated[DocumentType, Field(description=DOCUMENT_TYPE_CODES)]
    title: NonEmptyStr | None
    date: IsoDate | None


class LlmAnalysis(ApiModel):
    # First in the schema, so the model sets the language before it writes the summary in it.
    document: LlmDocument
    # One sentence per item, so the 3-5 rule is a list length: counting sentences in free text
    # trips over abbreviations ("sp. z o.o.", "Inc.") in every language.
    summary_sentences: Annotated[
        list[NonEmptyStr], Field(min_length=3, max_length=5, description=IN_DOCUMENT_LANGUAGE)
    ]
    key_points: Annotated[
        list[NonEmptyStr], Field(min_length=3, max_length=7, description=IN_DOCUMENT_LANGUAGE)
    ]
    entities: Entities
    amounts: list[Amount]
    dates: list[DateEntry]
    keywords: list[NonEmptyStr]
    suspicious_instructions: list[NonEmptyStr]

    @property
    def summary(self) -> str:
        return " ".join(self.summary_sentences)


def analysis_json_schema() -> dict[str, object]:
    schema = AnalysisResult.model_json_schema(by_alias=True)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def _without_keywords(node: Any, keywords: set[str]) -> Any:
    if isinstance(node, dict):
        return {k: _without_keywords(v, keywords) for k, v in node.items() if k not in keywords}
    if isinstance(node, list):
        return [_without_keywords(item, keywords) for item in node]
    return node


# Strict structured output rejects string-length, pattern and item-count constraints; they are
# still enforced locally when LlmAnalysis validates the answer.
LLM_JSON_SCHEMA: dict[str, Any] = _without_keywords(
    LlmAnalysis.model_json_schema(), {"minLength", "pattern", "minItems", "maxItems"}
)


if __name__ == "__main__":
    SCHEMA_PATH.write_text(json.dumps(analysis_json_schema(), indent=2, ensure_ascii=False) + "\n")
