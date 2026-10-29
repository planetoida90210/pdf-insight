import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)
from pydantic.alias_generators import to_camel

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
    file_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    pages: PageNumber
    language: Annotated[str, Field(pattern=r"^[a-z]{2}$")]
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


class AnalyzeRequest(ApiModel):
    extraction_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class LlmDocument(ApiModel):
    """Semantic document fields filled by the model (fileName/pages come from the backend)."""

    language: Annotated[str, Field(pattern=r"^[a-z]{2}$")]
    type: DocumentType
    title: NonEmptyStr | None
    date: IsoDate | None


class LlmAnalysis(ApiModel):
    """Model-facing payload: no fileName/pages/meta/warnings assembly."""

    document: LlmDocument
    summary: NonEmptyStr
    key_points: list[NonEmptyStr]
    entities: Entities
    amounts: list[Amount]
    dates: list[DateEntry]
    keywords: list[NonEmptyStr]
    suspicious_instructions: list[NonEmptyStr] = Field(default_factory=list)


def analysis_json_schema() -> dict[str, object]:
    schema = AnalysisResult.model_json_schema(by_alias=True)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def llm_json_schema() -> dict[str, object]:
    return LlmAnalysis.model_json_schema(by_alias=True)


if __name__ == "__main__":
    SCHEMA_PATH.write_text(json.dumps(analysis_json_schema(), indent=2, ensure_ascii=False) + "\n")
