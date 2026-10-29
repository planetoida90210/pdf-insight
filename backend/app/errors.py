"""Error and warning codes with their Polish messages (the only place user-facing texts live)."""

from enum import StrEnum
from functools import partial
from typing import Any

from app.schema import AnalysisWarning


class ErrorCode(StrEnum):
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    INVALID_PDF = "INVALID_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    NO_TEXT = "NO_TEXT"
    EXTRACTION_NOT_FOUND = "EXTRACTION_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DAILY_LIMIT = "DAILY_LIMIT"
    AI_INVALID_RESPONSE = "AI_INVALID_RESPONSE"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL = "INTERNAL"


class WarningCode(StrEnum):
    HIDDEN_TEXT = "HIDDEN_TEXT"
    OCR_USED = "OCR_USED"
    VISION_USED = "VISION_USED"
    OCR_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
    PAGES_SKIPPED = "PAGES_SKIPPED"
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    UNGROUNDED_REMOVED = "UNGROUNDED_REMOVED"
    CHUNKED = "CHUNKED"


ERRORS: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.FILE_TOO_LARGE: (413, "Plik jest za duży. Maksymalny rozmiar to {max_mb} MB."),
    ErrorCode.UNSUPPORTED_TYPE: (415, "Obsługiwane są tylko pliki PDF."),
    ErrorCode.INVALID_PDF: (422, "Plik jest uszkodzony albo nie jest poprawnym dokumentem PDF."),
    ErrorCode.ENCRYPTED_PDF: (
        422,
        "Plik PDF jest zabezpieczony hasłem. Usuń zabezpieczenie i spróbuj ponownie.",
    ),
    ErrorCode.TOO_MANY_PAGES: (
        422,
        "Dokument ma za dużo stron. Maksymalna liczba stron to {max_pages}.",
    ),
    ErrorCode.NO_TEXT: (422, "Nie udało się odczytać tekstu z dokumentu, również przez OCR."),
    ErrorCode.EXTRACTION_NOT_FOUND: (
        404,
        "Odczytany tekst wygasł albo nie istnieje. Wgraj plik ponownie.",
    ),
    ErrorCode.RATE_LIMITED: (429, "Zbyt wiele żądań. Spróbuj ponownie za chwilę."),
    ErrorCode.DAILY_LIMIT: (429, "Wyczerpano dzienny limit analiz. Spróbuj ponownie jutro."),
    ErrorCode.AI_INVALID_RESPONSE: (
        502,
        "Model AI zwrócił niepoprawną odpowiedź. Spróbuj ponownie.",
    ),
    ErrorCode.AI_UNAVAILABLE: (503, "Usługa AI jest chwilowo niedostępna. Spróbuj ponownie."),
    ErrorCode.TIMEOUT: (504, "Przetwarzanie trwało zbyt długo. Spróbuj ponownie."),
    ErrorCode.INVALID_REQUEST: (400, "Niepoprawne żądanie."),
    ErrorCode.NOT_FOUND: (404, "Nie znaleziono zasobu."),
    ErrorCode.INTERNAL: (500, "Wystąpił nieoczekiwany błąd serwera. Spróbuj ponownie."),
}

WARNINGS: dict[WarningCode, str] = {
    WarningCode.HIDDEN_TEXT: (
        'Na stronie {page} wykryto niewidoczny tekst: "{snippet}". Pominięto go w analizie.'
    ),
    WarningCode.OCR_USED: "Strona {page} nie ma warstwy tekstowej. Odczytano ją przez OCR.",
    WarningCode.VISION_USED: (
        "Strona {page} nie ma czytelnej warstwy tekstowej. Tekst odczytał model AI z obrazu."
    ),
    WarningCode.OCR_LOW_CONFIDENCE: "Strona {page}: niska pewność OCR ({confidence:.0f}%).",
    WarningCode.PAGES_SKIPPED: (
        "Strona {page} wymaga OCR, ale osiągnięto limit stron OCR ({limit}). Pominięto ją."
    ),
    WarningCode.INJECTION_SUSPECTED: (
        'Dokument zawiera fragment wyglądający na polecenie dla AI: "{snippet}". '
        "Potraktowano go jako dane, nie jako polecenie."
    ),
    WarningCode.UNGROUNDED_REMOVED: (
        "Usunięto kwoty lub daty, których nie znaleziono w tekście dokumentu (liczba: {count})."
    ),
    WarningCode.CHUNKED: (
        "Dokument był długi. Przeanalizowano go w {chunks} częściach i scalono wyniki."
    ),
}

SNIPPET_CHARS = 160


class ApiError(Exception):
    def __init__(
        self, code: ErrorCode, headers: dict[str, str] | None = None, **fields: object
    ) -> None:
        self.code = code
        self.status, template = ERRORS[code]
        self.message = template.format(**fields)
        self.headers = headers
        self.fields = fields
        super().__init__(code)

    def __reduce__(self) -> tuple[Any, ...]:
        # Errors raised in the extraction worker come back to the web process by pickle.
        return partial(ApiError, self.code, self.headers, **self.fields), ()


def warning(code: WarningCode, page: int | None = None, **fields: object) -> AnalysisWarning:
    if "snippet" in fields:
        fields["snippet"] = str(fields["snippet"])[:SNIPPET_CHARS]
    return AnalysisWarning(code=code, page=page, message=WARNINGS[code].format(page=page, **fields))
