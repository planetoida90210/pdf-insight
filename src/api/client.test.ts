import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import umowa from '../../schema/fixtures/valid/umowa.json';
import { AppError } from '../lib/errors';
import { analyzeExtraction, errorFromResponse, extractText } from './client';

const envelope = (code: string) => ({ error: { code, message: 'Komunikat serwera' } });
const signal = () => new AbortController().signal;

describe('errorFromResponse', () => {
  it('maps the envelope code to a Polish message', () => {
    const error = errorFromResponse(415, envelope('UNSUPPORTED_TYPE'), null);
    expect(error.code).toBe('UNSUPPORTED_TYPE');
    expect(error.message).toBe('To nie jest plik PDF.');
    expect(error.retryable).toBe(false);
    expect(errorFromResponse(422, envelope('TEXT_TOO_LONG'), null).retryable).toBe(false);
  });

  it('maps INVALID_REQUEST and NOT_FOUND to Polish messages', () => {
    const invalid = errorFromResponse(400, envelope('INVALID_REQUEST'), null);
    expect(invalid.code).toBe('INVALID_REQUEST');
    expect(invalid.message).toBe('Serwer odrzucił żądanie.');
    expect(invalid.retryable).toBe(true);

    const missing = errorFromResponse(404, envelope('NOT_FOUND'), null);
    expect(missing.code).toBe('NOT_FOUND');
    expect(missing.message).toBe('Serwer nie zna tego adresu.');
    expect(missing.retryable).toBe(true);
  });

  it('marks transient errors as retryable', () => {
    expect(errorFromResponse(500, envelope('AI_UNAVAILABLE'), null).retryable).toBe(true);
    expect(errorFromResponse(500, envelope('AI_INVALID_RESPONSE'), null).retryable).toBe(true);
    expect(errorFromResponse(404, envelope('EXTRACTION_NOT_FOUND'), null).retryable).toBe(true);
  });

  it('gives the wait time from the Retry-After header', () => {
    expect(errorFromResponse(429, envelope('RATE_LIMITED'), '30').message).toBe(
      'Za dużo zapytań, spróbuj za 30 s.',
    );
    expect(errorFromResponse(429, envelope('RATE_LIMITED'), 'tomorrow').message).toBe(
      'Za dużo zapytań, odczekaj chwilę.',
    );
  });

  it('falls back to the HTTP status without a known code', () => {
    expect(errorFromResponse(413, '<html>Payload Too Large</html>', null).code).toBe(
      'FILE_TOO_LARGE',
    );
    expect(errorFromResponse(429, null, null).code).toBe('RATE_LIMITED');
    expect(errorFromResponse(504, null, null).code).toBe('TIMEOUT');
    expect(errorFromResponse(500, envelope('UNKNOWN'), null).code).toBe('INTERNAL');
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

  it('sends the id and returns the validated result', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(umowa)));
    vi.stubGlobal('fetch', fetchMock);

    const result = await analyzeExtraction('abc', signal());

    expect(result.document.type).toBe('umowa');
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/api/analyze',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ extractionId: 'abc' }) }),
    );
  });

  it('rejects a result that does not match the schema', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(Response.json({ ...umowa, summary: '' })));
    await expect(analyzeExtraction('abc', signal())).rejects.toMatchObject({
      code: 'INVALID_RESULT',
    });
  });

  it('turns an error response into an AppError', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(Response.json(envelope('AI_UNAVAILABLE'), { status: 500 })),
    );
    await expect(analyzeExtraction('abc', signal())).rejects.toMatchObject({
      code: 'AI_UNAVAILABLE',
    });
  });

  it('tells a network failure from a cancel', async () => {
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

  it('a cancel while the body is read gives ABORTED, not INVALID_RESULT', async () => {
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

describe('extractText', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_URL', 'https://api.example.test');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('sends the browser OCR as a JSON file part, and no part without it', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(new Response(null)));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-1.7'], 'skan.pdf', { type: 'application/pdf' });
    const ocr = [{ page: 1, text: 'Aneks', confidence: 90 }];

    await extractText(file, ocr, signal()).catch(() => null);
    await extractText(file, [], signal()).catch(() => null);

    const [withOcr, without] = fetchMock.mock.calls.map(([, init]) => init?.body as FormData);
    const part = withOcr?.get('ocr');
    expect(part).toBeInstanceOf(Blob);
    expect(JSON.parse(await (part as Blob).text())).toEqual(ocr);
    expect(without?.has('ocr')).toBe(false);
  });
});
