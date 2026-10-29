import { z } from 'zod';
import { AppError, isErrorCode } from '../lib/errors';
import {
  analysisResultSchema,
  extractResponseSchema,
  type AnalysisResult,
  type ExtractResponse,
} from '../lib/schema';

// OCR i model AI potrafią działać długo, ale nie dłużej niż limit czasu po stronie serwera.
const REQUEST_TIMEOUT_MS = 120_000;
const HEALTH_TIMEOUT_MS = 5_000;

const errorEnvelopeSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

export const healthResponseSchema = z.object({
  status: z.literal('ok'),
  provider: z.enum(['gemini', 'anthropic']),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;
export type AiProvider = HealthResponse['provider'];

export const PROVIDER_LABELS: Record<AiProvider, string> = {
  gemini: 'Google Gemini',
  anthropic: 'Anthropic Claude',
};

export const FALLBACK_PROVIDER_LABEL = 'zewnętrzne API AI';

function apiUrl(path: string): string {
  return `${import.meta.env.VITE_API_URL.replace(/\/+$/, '')}${path}`;
}

function retryAfterMessage(header: string | null): string | undefined {
  const seconds = Number(header);
  if (!header || !Number.isInteger(seconds) || seconds <= 0) return undefined;
  return `Zbyt wiele zapytań w krótkim czasie. Spróbuj ponownie za ${seconds} s.`;
}

// Komunikat zawsze pochodzi z naszej mapy kodów, więc treść od serwera nie trafia do interfejsu bez kontroli.
export function errorFromResponse(
  status: number,
  body: unknown,
  retryAfter: string | null,
): AppError {
  const envelope = errorEnvelopeSchema.safeParse(body);
  const code = envelope.success ? envelope.data.error.code : '';

  if (code === 'RATE_LIMITED') return new AppError('RATE_LIMITED', retryAfterMessage(retryAfter));
  if (isErrorCode(code)) return new AppError(code);
  if (status === 413) return new AppError('FILE_TOO_LARGE');
  if (status === 429) return new AppError('RATE_LIMITED', retryAfterMessage(retryAfter));
  if (status === 504) return new AppError('TIMEOUT');
  if (status === 503) return new AppError('AI_UNAVAILABLE');
  return new AppError('INTERNAL');
}

async function request(path: string, init: RequestInit, signal: AbortSignal): Promise<unknown> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  let response: Response;
  let body: unknown;
  try {
    response = await fetch(apiUrl(path), { ...init, signal: AbortSignal.any([signal, timeout]) });
    body = await response.json().catch(() => null);
  } catch {
    if (signal.aborted) throw new AppError('ABORTED');
    if (timeout.aborted) throw new AppError('TIMEOUT');
    throw new AppError('NETWORK');
  }
  if (!response.ok) {
    throw errorFromResponse(response.status, body, response.headers.get('Retry-After'));
  }
  return body;
}

// Wywołanie na starcie budzi backend i pozwala nazwać dostawcę AI w informacji o prywatności.
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse | null> {
  const timeout = AbortSignal.timeout(HEALTH_TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  try {
    const response = await fetch(apiUrl('/api/health'), { method: 'GET', signal: combined });
    if (!response.ok) return null;
    const body: unknown = await response.json().catch(() => null);
    const parsed = healthResponseSchema.safeParse(body);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export async function extractText(file: File, signal: AbortSignal): Promise<ExtractResponse> {
  const form = new FormData();
  form.append('file', file);
  const body = await request('/api/extract', { method: 'POST', body: form }, signal);
  const parsed = extractResponseSchema.safeParse(body);
  if (!parsed.success) throw new AppError('INVALID_RESULT');
  return parsed.data;
}

// Wynik AI jest walidowany schematem przed wyświetleniem (F-04).
export async function analyzeExtraction(
  extractionId: string,
  signal: AbortSignal,
): Promise<AnalysisResult> {
  const body = await request(
    '/api/analyze',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extractionId }),
    },
    signal,
  );
  const parsed = analysisResultSchema.safeParse(body);
  if (!parsed.success) throw new AppError('INVALID_RESULT');
  return parsed.data;
}
