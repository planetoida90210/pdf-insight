import { MAX_FILE_MB } from './config';

// Kody z koperty błędów backendu plus kody nadawane przez frontend (NETWORK, INVALID_RESULT, ABORTED).
const MESSAGES = {
  FILE_TOO_LARGE: `Plik ma ponad ${MAX_FILE_MB} MB.`,
  UNSUPPORTED_TYPE: 'To nie jest plik PDF.',
  INVALID_PDF: 'Plik PDF jest uszkodzony.',
  ENCRYPTED_PDF: 'PDF jest chroniony hasłem.',
  TOO_MANY_PAGES: 'Dokument ma za dużo stron.',
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
