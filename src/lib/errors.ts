import { MAX_FILE_MB } from './config';

// Codes from the backend's error envelope plus the frontend's own (NETWORK, INVALID_RESULT, ABORTED,
// FILE_UNREADABLE).
const MESSAGES = {
  FILE_TOO_LARGE: `Plik ma ponad ${MAX_FILE_MB} MB.`,
  UNSUPPORTED_TYPE: 'To nie jest plik PDF.',
  INVALID_PDF: 'Plik PDF jest uszkodzony.',
  ENCRYPTED_PDF: 'PDF jest chroniony hasłem.',
  TOO_MANY_PAGES: 'Dokument ma za dużo stron.',
  TEXT_TOO_LONG: 'Dokument ma za dużo tekstu.',
  NO_TEXT: 'Nie udało się odczytać tekstu.',
  EXTRACTION_NOT_FOUND: 'Odczytany tekst wygasł na serwerze.',
  RATE_LIMITED: 'Za dużo zapytań, odczekaj chwilę.',
  DAILY_LIMIT: 'Wyczerpano dzienny limit analiz.',
  AI_INVALID_RESPONSE: 'AI zwróciło niepoprawny wynik.',
  AI_UNAVAILABLE: 'Usługa AI jest chwilowo niedostępna.',
  TIMEOUT: 'Analiza trwała zbyt długo.',
  INTERNAL: 'Wystąpił błąd serwera.',
  INVALID_REQUEST: 'Serwer odrzucił żądanie.',
  NOT_FOUND: 'Serwer nie zna tego adresu.',
  NETWORK: 'Brak połączenia z serwerem.',
  INVALID_RESULT: 'Wynik jest niezgodny ze schematem.',
  ABORTED: 'Analiza anulowana.',
  FILE_UNREADABLE: 'Przeglądarka nie może odczytać tego pliku.',
} as const;

export type ErrorCode = keyof typeof MESSAGES;

// A retry cannot help when the problem is the file itself or the daily limit.
const FINAL_CODES: ReadonlySet<ErrorCode> = new Set([
  'FILE_TOO_LARGE',
  'UNSUPPORTED_TYPE',
  'INVALID_PDF',
  'ENCRYPTED_PDF',
  'TOO_MANY_PAGES',
  'TEXT_TOO_LONG',
  'NO_TEXT',
  'DAILY_LIMIT',
  'FILE_UNREADABLE',
]);

// Reading a file that was moved or deleted after it was picked, or a cloud placeholder, rejects
// with one of these.
const FILE_READ_ERRORS: ReadonlySet<string> = new Set(['NotReadableError', 'NotFoundError']);

export function isErrorCode(value: string): value is ErrorCode {
  return Object.hasOwn(MESSAGES, value);
}

export function retryAfterMessage(seconds: number): string {
  return `Za dużo zapytań, spróbuj za ${seconds} s.`;
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

export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  if (error instanceof DOMException && FILE_READ_ERRORS.has(error.name)) {
    return new AppError('FILE_UNREADABLE');
  }
  return new AppError('INTERNAL');
}
