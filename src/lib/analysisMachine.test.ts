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
import { validatePdf } from './pdf';
import { analysisResultSchema, type ExtractResponse } from './schema';

vi.mock('../api/client', () => ({ extractText: vi.fn(), analyzeExtraction: vi.fn() }));
vi.mock('./pdf', () => ({ validatePdf: vi.fn() }));

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

const running: AnalysisState = {
  phase: 'running',
  startedAt: 1,
  file,
  step: 2,
  extraction: extraction('e1'),
};

describe('analysisReducer', () => {
  it('start ustawia przebieg od podanego kroku', () => {
    const run: Run = { file, step: 2, extraction: extraction('e1') };
    expect(analysisReducer(IDLE, { type: 'start', run, startedAt: 5 })).toEqual({
      phase: 'running',
      startedAt: 5,
      ...run,
    });
  });

  it('odczyt tekstu kasuje stary odczyt, a analiza go zapisuje', () => {
    const extracting = analysisReducer(running, { type: 'extracting' });
    expect(extracting).toMatchObject({ step: 1, extraction: null });
    const analyzing = analysisReducer(extracting, {
      type: 'analyzing',
      extraction: extraction('e2'),
    });
    expect(analyzing).toMatchObject({ step: 2, extraction: { extractionId: 'e2' } });
  });

  it('błąd zapamiętuje krok i odczyt, żeby ponowić tylko ten krok', () => {
    const error = new AppError('AI_UNAVAILABLE');
    expect(analysisReducer(running, { type: 'fail', error })).toEqual({
      phase: 'error',
      file,
      step: 2,
      extraction: extraction('e1'),
      error,
    });
  });

  it('kończy się wynikiem i wraca do stanu pustego po resecie', () => {
    const done = analysisReducer(running, { type: 'done', result });
    expect(done).toEqual({ phase: 'done', file, result });
    expect(analysisReducer(done, { type: 'reset' })).toBe(IDLE);
  });

  it('ignoruje zdarzenia przebiegu poza fazą running', () => {
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
    vi.mocked(validatePdf).mockReset().mockResolvedValue(12);
    vi.mocked(extractText).mockReset().mockResolvedValue(extraction('e1'));
    vi.mocked(analyzeExtraction).mockReset().mockResolvedValue(result);
  });

  it('przechodzi walidację, odczyt i analizę', async () => {
    const signal = new AbortController().signal;
    await expect(runPipeline({ file, step: 0, extraction: null }, signal, dispatch)).resolves.toBe(
      result,
    );
    expect(types()).toEqual(['start', 'extracting', 'analyzing', 'done']);
    expect(validatePdf).toHaveBeenCalledWith(file);
    expect(analyzeExtraction).toHaveBeenCalledWith('e1', signal);
  });

  it('ponowienie analizy nie wysyła pliku drugi raz', async () => {
    const run: Run = { file, step: 2, extraction: extraction('e1') };
    await runPipeline(run, new AbortController().signal, dispatch);
    expect(validatePdf).not.toHaveBeenCalled();
    expect(extractText).not.toHaveBeenCalled();
    expect(types()).toEqual(['start', 'analyzing', 'done']);
  });

  it('po wygaśnięciu odczytu wysyła plik ponownie, ale tylko raz', async () => {
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

  it('po anulowaniu nie zmienia już stanu', async () => {
    const controller = new AbortController();
    vi.mocked(validatePdf).mockImplementation(async () => {
      controller.abort();
      return 12;
    });
    vi.mocked(extractText).mockRejectedValue(new AppError('ABORTED'));
    await expect(
      runPipeline({ file, step: 0, extraction: null }, controller.signal, dispatch),
    ).resolves.toBeNull();
    expect(types()).toEqual(['start']);
  });

  it('nieznany wyjątek zamienia na błąd INTERNAL', async () => {
    vi.mocked(validatePdf).mockRejectedValue(new TypeError('chunk load failed'));
    await runPipeline({ file, step: 0, extraction: null }, new AbortController().signal, dispatch);
    expect(actions.at(-1)).toMatchObject({ type: 'fail', error: { code: 'INTERNAL' } });
  });
});

describe('statusMessage', () => {
  it('opisuje fazę po polsku', () => {
    expect(statusMessage(IDLE)).toMatch(/Gotowy/);
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
