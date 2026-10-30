import type { Worker } from 'tesseract.js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import umowa from '../../schema/fixtures/valid/umowa.json';
import { analyzeExtraction, extractText } from '../api/client';
import {
  analysisReducer,
  IDLE,
  runPipeline,
  statusMessage,
  type AnalysisAction,
  type AnalysisState,
  type Run,
} from './analysisMachine';
import { AppError } from './errors';
import { readScannedPages, startOcrWorker, stopOcrWorker, type OcrPage } from './ocr';
import { validatePdf } from './pdf';
import { analysisResultSchema, type ExtractResponse } from './schema';

vi.mock('../api/client', () => ({ extractText: vi.fn(), analyzeExtraction: vi.fn() }));
vi.mock('./pdf', () => ({ validatePdf: vi.fn() }));
vi.mock('./ocr', () => ({
  readScannedPages: vi.fn(),
  startOcrWorker: vi.fn(),
  stopOcrWorker: vi.fn(),
}));

const file = new File(['%PDF-1.4'], 'umowa.pdf', { type: 'application/pdf' });
const result = analysisResultSchema.parse(umowa);
const extraction = (extractionId: string): ExtractResponse => ({
  extractionId,
  fileName: 'umowa.pdf',
  pages: 12,
  chars: 100,
  pageInfo: [],
  warnings: [],
  expiresAt: '2026-10-29T18:15:00Z',
});
const notFound = new AppError('EXTRACTION_NOT_FOUND');

const ocrPages: OcrPage[] = [{ page: 11, text: 'Aneks nr 1', confidence: 91 }];
const ocrWorker = Promise.resolve({} as Worker);

const running: AnalysisState = {
  phase: 'running',
  startedAt: 1,
  ocr: null,
  file,
  step: 2,
  extraction: extraction('e1'),
};

describe('analysisReducer', () => {
  it('start sets the run at the given step', () => {
    const run: Run = { file, step: 2, extraction: extraction('e1') };
    expect(analysisReducer(IDLE, { type: 'start', run, startedAt: 5 })).toEqual({
      phase: 'running',
      startedAt: 5,
      ocr: null,
      ...run,
    });
  });

  it('extracting clears the old extraction and analyzing stores the new one', () => {
    const extracting = analysisReducer(running, { type: 'extracting' });
    expect(extracting).toMatchObject({ step: 1, extraction: null, ocr: null });
    const progress = { done: 2, total: 5 };
    expect(analysisReducer(extracting, { type: 'ocr', progress })).toMatchObject({ ocr: progress });
    const read = analysisReducer(extracting, { type: 'ocr', progress: { done: 3, total: 3 } });
    const analyzing = analysisReducer(read, {
      type: 'analyzing',
      extraction: extraction('e2'),
    });
    expect(analyzing).toMatchObject({ step: 2, extraction: { extractionId: 'e2' }, ocr: null });
  });

  it('a failure keeps the step and extraction, so only that step is retried', () => {
    const error = new AppError('AI_UNAVAILABLE');
    expect(analysisReducer(running, { type: 'fail', error })).toEqual({
      phase: 'error',
      file,
      step: 2,
      extraction: extraction('e1'),
      error,
    });
  });

  it('ends with the result and returns to idle on reset', () => {
    const done = analysisReducer(running, { type: 'done', result });
    expect(done).toEqual({ phase: 'done', file, result });
    expect(analysisReducer(done, { type: 'reset' })).toBe(IDLE);
  });

  it('ignores run actions outside the running phase', () => {
    expect(analysisReducer(IDLE, { type: 'done', result })).toBe(IDLE);
    expect(analysisReducer(IDLE, { type: 'extracting' })).toBe(IDLE);
  });
});

describe('runPipeline', () => {
  const actions: AnalysisAction[] = [];
  const dispatch = (action: AnalysisAction) => actions.push(action);
  const types = () => actions.map((action) => action.type);

  beforeEach(() => {
    actions.length = 0;
    vi.mocked(validatePdf).mockReset().mockResolvedValue();
    vi.mocked(readScannedPages).mockReset().mockResolvedValue(ocrPages);
    vi.mocked(startOcrWorker).mockReset().mockReturnValue(ocrWorker);
    vi.mocked(stopOcrWorker).mockReset();
    vi.mocked(extractText).mockReset().mockResolvedValue(extraction('e1'));
    vi.mocked(analyzeExtraction).mockReset().mockResolvedValue(result);
  });

  it('runs validation, extraction and analysis', async () => {
    const signal = new AbortController().signal;
    await expect(runPipeline({ file, step: 0, extraction: null }, signal, dispatch)).resolves.toBe(
      result,
    );
    expect(types()).toEqual(['start', 'extracting', 'analyzing', 'done']);
    expect(validatePdf).toHaveBeenCalledWith(file);
    expect(extractText).toHaveBeenCalledWith(file, ocrPages, signal);
    expect(analyzeExtraction).toHaveBeenCalledWith('e1', signal);
  });

  it('starts the OCR worker before the file checks and ends it with the run', async () => {
    await runPipeline({ file, step: 0, extraction: null }, new AbortController().signal, dispatch);
    const [started] = vi.mocked(startOcrWorker).mock.invocationCallOrder;
    const [checked] = vi.mocked(validatePdf).mock.invocationCallOrder;
    expect(started).toBeLessThan(checked ?? 0);
    expect(startOcrWorker).toHaveBeenCalledOnce();
    expect(readScannedPages).toHaveBeenCalledWith(
      file,
      ocrWorker,
      expect.anything(),
      expect.anything(),
    );
    expect(stopOcrWorker).toHaveBeenCalledWith(ocrWorker);
  });

  it('ends the OCR worker when the file checks fail', async () => {
    vi.mocked(validatePdf).mockRejectedValue(new AppError('INVALID_PDF'));
    await runPipeline({ file, step: 0, extraction: null }, new AbortController().signal, dispatch);
    expect(readScannedPages).not.toHaveBeenCalled();
    expect(stopOcrWorker).toHaveBeenCalledWith(ocrWorker);
  });

  it('reports the OCR progress and sends the file without the OCR text after an OCR failure', async () => {
    vi.mocked(readScannedPages).mockImplementation(async (_, __, ___, onProgress) => {
      onProgress(1, 2);
      throw new Error('worker failed to load');
    });
    const signal = new AbortController().signal;
    await runPipeline({ file, step: 0, extraction: null }, signal, dispatch);
    expect(actions).toContainEqual({ type: 'ocr', progress: { done: 1, total: 2 } });
    expect(extractText).toHaveBeenCalledWith(file, [], signal);
    expect(types().at(-1)).toBe('done');
  });

  it('an analysis retry does not upload the file again', async () => {
    const run: Run = { file, step: 2, extraction: extraction('e1') };
    await runPipeline(run, new AbortController().signal, dispatch);
    expect(validatePdf).not.toHaveBeenCalled();
    expect(extractText).not.toHaveBeenCalled();
    expect(startOcrWorker).not.toHaveBeenCalled();
    expect(types()).toEqual(['start', 'analyzing', 'done']);
  });

  it('uploads the file again once after the extraction expired', async () => {
    vi.mocked(extractText).mockResolvedValueOnce(extraction('e2'));
    vi.mocked(analyzeExtraction).mockRejectedValueOnce(notFound);
    const run: Run = { file, step: 2, extraction: extraction('e1') };
    await expect(runPipeline(run, new AbortController().signal, dispatch)).resolves.toBe(result);
    expect(analyzeExtraction).toHaveBeenLastCalledWith('e2', expect.anything());

    actions.length = 0;
    vi.mocked(analyzeExtraction).mockRejectedValue(notFound);
    await expect(runPipeline(run, new AbortController().signal, dispatch)).resolves.toBeNull();
    expect(analyzeExtraction).toHaveBeenCalledTimes(4);
    expect(actions.at(-1)).toEqual({ type: 'fail', error: notFound });
  });

  it('changes no state after a cancel', async () => {
    const controller = new AbortController();
    vi.mocked(validatePdf).mockImplementation(async () => {
      controller.abort();
    });
    vi.mocked(extractText).mockRejectedValue(new AppError('ABORTED'));
    await expect(
      runPipeline({ file, step: 0, extraction: null }, controller.signal, dispatch),
    ).resolves.toBeNull();
    expect(types()).toEqual(['start']);
  });

  it('turns a file the browser cannot read into FILE_UNREADABLE', async () => {
    vi.mocked(validatePdf).mockRejectedValue(new DOMException('gone', 'NotReadableError'));
    await runPipeline({ file, step: 0, extraction: null }, new AbortController().signal, dispatch);
    expect(actions.at(-1)).toMatchObject({
      type: 'fail',
      error: { code: 'FILE_UNREADABLE', retryable: false },
    });
  });

  it('turns an unknown exception into INTERNAL', async () => {
    vi.mocked(validatePdf).mockRejectedValue(new TypeError('chunk load failed'));
    await runPipeline({ file, step: 0, extraction: null }, new AbortController().signal, dispatch);
    expect(actions.at(-1)).toMatchObject({ type: 'fail', error: { code: 'INTERNAL' } });
  });
});

describe('statusMessage', () => {
  it('describes the phase in Polish', () => {
    expect(statusMessage(IDLE)).toBe('Wybierz plik PDF.');
    expect(statusMessage({ ...running, step: 1 })).toBe('Trwa: Odczyt tekstu');
    expect(
      statusMessage({
        phase: 'error',
        file,
        step: 1,
        extraction: null,
        error: new AppError('NETWORK'),
      }),
    ).toBe(new AppError('NETWORK').message);
    expect(statusMessage({ phase: 'done', file, result })).toBe(
      `Analiza zakończona: ${result.document.title}`,
    );
  });
});
