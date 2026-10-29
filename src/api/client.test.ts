import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import umowa from '../../schema/fixtures/valid/umowa.json';
import { AppError } from '../lib/errors';
import { analyzeExtraction, errorFromResponse } from './client';

const envelope = (code: string) => ({ error: { code, message: 'Komunikat serwera' } });
const signal = () => new AbortController().signal;

describe('errorFromResponse', () => {
  it('mapuje kod z koperty błędu na polski komunikat', () => {
    const error = errorFromResponse(415, envelope('UNSUPPORTED_TYPE'), null);
    expect(error.code).toBe('UNSUPPORTED_TYPE');
    expect(error.message).toBe('To nie jest plik PDF.');
    expect(error.retryable).toBe(false);
  });

  it('mapuje INVALID_REQUEST i NOT_FOUND na polskie komunikaty', () => {
    const invalid = errorFromResponse(400, envelope('INVALID_REQUEST'), null);
    expect(invalid.code).toBe('INVALID_REQUEST');
    expect(invalid.message).toBe('Serwer odrzucił żądanie.');
    expect(invalid.retryable).toBe(true);

    const missing = errorFromResponse(404, envelope('NOT_FOUND'), null);
    expect(missing.code).toBe('NOT_FOUND');
    expect(missing.message).toBe('Serwer nie zna tego adresu.');
    expect(missing.retryable).toBe(true);
  });

  it('oznacza błędy przejściowe jako możliwe do ponowienia', () => {
    expect(errorFromResponse(503, envelope('AI_UNAVAILABLE'), null).retryable).toBe(true);
    expect(errorFromResponse(502, envelope('AI_INVALID_RESPONSE'), null).retryable).toBe(true);
    expect(errorFromResponse(404, envelope('EXTRACTION_NOT_FOUND'), null).retryable).toBe(true);
  });

  it('podaje czas oczekiwania z nagłówka Retry-After', () => {
    expect(errorFromResponse(429, envelope('RATE_LIMITED'), '30').message).toBe(
      'Za dużo zapytań, spróbuj za 30 s.',
    );
    expect(errorFromResponse(429, envelope('RATE_LIMITED'), 'jutro').message).toBe(
      'Za dużo zapytań, odczekaj chwilę.',
    );
  });

  it('bez znanego kodu korzysta ze statusu HTTP', () => {
    expect(errorFromResponse(413, '<html>Payload Too Large</html>', null).code).toBe(
      'FILE_TOO_LARGE',
    );
    expect(errorFromResponse(429, null, null).code).toBe('RATE_LIMITED');
    expect(errorFromResponse(504, null, null).code).toBe('TIMEOUT');
    expect(errorFromResponse(500, envelope('NIEZNANY'), null).code).toBe('INTERNAL');
  });
});

describe('analyzeExtraction', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_URL', 'https://api.example.test/');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('wysyła identyfikator i zwraca zwalidowany wynik', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(umowa)));
    vi.stubGlobal('fetch', fetchMock);

    const result = await analyzeExtraction('abc', signal());

    expect(result.document.type).toBe('umowa');
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/api/analyze',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ extractionId: 'abc' }) }),
    );
  });

  it('odrzuca wynik niezgodny ze schematem', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(Response.json({ ...umowa, summary: '' })));
    await expect(analyzeExtraction('abc', signal())).rejects.toMatchObject({
      code: 'INVALID_RESULT',
    });
  });

  it('zamienia odpowiedź z błędem na AppError', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(Response.json(envelope('AI_UNAVAILABLE'), { status: 503 })),
    );
    await expect(analyzeExtraction('abc', signal())).rejects.toMatchObject({
      code: 'AI_UNAVAILABLE',
    });
  });

  it('rozróżnia brak sieci i anulowanie przez użytkownika', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
    await expect(analyzeExtraction('abc', signal())).rejects.toMatchObject({ code: 'NETWORK' });

    const controller = new AbortController();
    controller.abort();
    const error: unknown = await analyzeExtraction('abc', controller.signal).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(AppError);
    expect(error).toMatchObject({ code: 'ABORTED' });
  });

  it('anulowanie w trakcie czytania odpowiedzi daje ABORTED, a nie INVALID_RESULT', async () => {
    const controller = new AbortController();
    const response = Response.json(umowa);
    vi.spyOn(response, 'json').mockImplementation(() => {
      controller.abort();
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    });
    vi.stubGlobal('fetch', () => Promise.resolve(response));
    await expect(analyzeExtraction('abc', controller.signal)).rejects.toMatchObject({
      code: 'ABORTED',
    });
  });
});
