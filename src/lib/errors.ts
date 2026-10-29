// Kody z kopertą błędów backendu plus kody, które nadaje sam frontend (NETWORK, INVALID_RESULT, ABORTED).
const MESSAGES = {
  FILE_TOO_LARGE: 'Plik jest większy niż 10 MB. Wybierz mniejszy plik.',
  UNSUPPORTED_TYPE: 'To nie jest plik PDF. Wybierz plik w formacie PDF.',
  INVALID_PDF: 'Nie udało się otworzyć pliku. PDF jest uszkodzony lub niepoprawny.',
  ENCRYPTED_PDF: 'PDF jest zabezpieczony hasłem. Zdejmij zabezpieczenie i wgraj plik ponownie.',
  TOO_MANY_PAGES: 'Dokument ma więcej stron, niż pozwala limit analizy.',
  NO_TEXT: 'Nie udało się odczytać tekstu z dokumentu, także przez OCR.',
  EXTRACTION_NOT_FOUND:
    'Odczytany tekst wygasł na serwerze. Spróbuj ponownie, a plik zostanie wysłany jeszcze raz.',
  RATE_LIMITED: 'Zbyt wiele zapytań w krótkim czasie. Odczekaj chwilę i spróbuj ponownie.',
  DAILY_LIMIT: 'Wyczerpano dzienny limit analiz w wersji demo. Spróbuj ponownie jutro.',
  AI_INVALID_RESPONSE: 'Model AI zwrócił niepoprawny wynik. Spróbuj ponownie.',
  AI_UNAVAILABLE: 'Usługa AI jest chwilowo niedostępna. Spróbuj ponownie za chwilę.',
  TIMEOUT: 'Przetwarzanie trwało zbyt długo i zostało przerwane. Spróbuj ponownie.',
  INTERNAL: 'Wystąpił nieoczekiwany błąd serwera. Spróbuj ponownie.',
  NETWORK: 'Brak połączenia z serwerem. Sprawdź internet i spróbuj ponownie.',
  INVALID_RESULT: 'Serwer zwrócił wynik niezgodny ze schematem. Spróbuj ponownie.',
  ABORTED: 'Analiza została anulowana.',
} as const;

export type ErrorCode = keyof typeof MESSAGES;

// Ponowienie nic nie zmieni, gdy problem leży w samym pliku albo w dziennym limicie.
const FINAL_CODES: ReadonlySet<ErrorCode> = new Set([
  'FILE_TOO_LARGE',
  'UNSUPPORTED_TYPE',
  'INVALID_PDF',
  'ENCRYPTED_PDF',
  'TOO_MANY_PAGES',
  'NO_TEXT',
  'DAILY_LIMIT',
]);

export function isErrorCode(value: string): value is ErrorCode {
  return Object.hasOwn(MESSAGES, value);
}

export class AppError extends Error {
  readonly code: ErrorCode;
  readonly retryable: boolean;

  constructor(code: ErrorCode, message: string = MESSAGES[code]) {
    super(message);
    this.name = 'AppError';
    this.code = code;
    this.retryable = !FINAL_CODES.has(code);
  }
}
