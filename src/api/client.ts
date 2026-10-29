import { z } from 'zod';
import { AppError, isErrorCode, retryAfterMessage, type ErrorCode } from '../lib/errors';
import {
  analysisResultSchema,
  extractResponseSchema,
  healthResponseSchema,
  type AiProvider,
  type AnalysisResult,
  type ExtractResponse,
} from '../lib/schema';

// OCR i model AI potrafią działać długo, ale nie dłużej niż limit czasu po stronie serwera.
const REQUEST_TIMEOUT_MS = 120_000;
const HEALTH_TIMEOUT_MS = 5_000;

// Kod HTTP decyduje tylko wtedy, gdy odpowiedź nie ma koperty z naszym kodem błędu.
const CODE_BY_STATUS: Partial<Record<number, ErrorCode>> = {
  413: 'FILE_TOO_LARGE',
  429: 'RATE_LIMITED',
  503: 'AI_UNAVAILABLE',
  504: 'TIMEOUT',
};

const errorEnvelopeSchema = z.object({ error: z.object({ code: z.string() }) });

export const PROVIDER_LABELS: Record<AiProvider, string> = {
  gemini: 'Google Gemini',
  anthropic: 'Anthropic Claude',
};

export const FALLBACK_PROVIDER_LABEL = 'zewnętrzne API AI';

function apiUrl(path: string): string {
  return `${import.meta.env.VITE_API_URL.replace(/\/+$/, '')}${path}`;
}

function errorCode(status: number, body: unknown): ErrorCode {
  const envelope = errorEnvelopeSchema.safeParse(body);
  const code = envelope.success ? envelope.data.error.code : '';
  return isErrorCode(code) ? code : (CODE_BY_STATUS[status] ?? 'INTERNAL');
}

// Komunikat zawsze pochodzi z naszej mapy kodów, więc treść od serwera nie trafia do interfejsu.
export function errorFromResponse(
  status: number,
  body: unknown,
  retryAfter: string | null,
): AppError {
  const code = errorCode(status, body);
  const seconds = Number(retryAfter);
  if (code === 'RATE_LIMITED' && Number.isInteger(seconds) && seconds > 0) {
    return new AppError(code, retryAfterMessage(seconds));
  }
  return new AppError(code);
}

// Ciało błędu z proxy bywa HTML-em, więc nieczytelne ciało traktujemy jak jego brak.
async function send(
  path: string,
  init: RequestInit,
  signal: AbortSignal,
  timeoutMs: number,
): Promise<{ response: Response; body: unknown }> {
  const combined = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]);
  try {
    const response = await fetch(apiUrl(path), { ...init, signal: combined });
    const body: unknown = await response.json().catch(() => null);
    combined.throwIfAborted();
    return { response, body };
  } catch {
    if (signal.aborted) throw new AppError('ABORTED');
    throw new AppError(combined.aborted ? 'TIMEOUT' : 'NETWORK');
  }
}

async function request<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  signal: AbortSignal,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const { response, body } = await send(path, init, signal, timeoutMs);
  if (!response.ok) {
    throw errorFromResponse(response.status, body, response.headers.get('Retry-After'));
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new AppError('INVALID_RESULT');
  return parsed.data;
}

// Budzi backend przy starcie i podaje dostawcę AI do informacji o prywatności. Błąd = brak nazwy.
export function fetchHealth(signal: AbortSignal): Promise<AiProvider | null> {
  return request('/api/health', {}, healthResponseSchema, signal, HEALTH_TIMEOUT_MS).then(
    (health) => health.provider,
    () => null,
  );
}

export function extractText(file: File, signal: AbortSignal): Promise<ExtractResponse> {
  const body = new FormData();
  body.append('file', file);
  return request('/api/extract', { method: 'POST', body }, extractResponseSchema, signal);
}

// Wynik AI jest walidowany schematem przed wyświetleniem (F-04).
export function analyzeExtraction(
  extractionId: string,
  signal: AbortSignal,
): Promise<AnalysisResult> {
  const init = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ extractionId }),
  };
  return request('/api/analyze', init, analysisResultSchema, signal);
}
