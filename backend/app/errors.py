from enum import StrEnum


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


ERRORS: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.FILE_TOO_LARGE: (413, "Plik jest za duży."),
    ErrorCode.UNSUPPORTED_TYPE: (415, "Obsługiwane są tylko pliki PDF."),
    ErrorCode.INVALID_PDF: (422, "Plik jest uszkodzony albo nie jest poprawnym dokumentem PDF."),
    ErrorCode.ENCRYPTED_PDF: (
        422,
        "Plik PDF jest zabezpieczony hasłem. Usuń zabezpieczenie i spróbuj ponownie.",
    ),
    ErrorCode.TOO_MANY_PAGES: (422, "Dokument ma za dużo stron."),
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


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.status, default_message = ERRORS[code]
        self.message = message or default_message
        self.headers = headers
        super().__init__(code)
