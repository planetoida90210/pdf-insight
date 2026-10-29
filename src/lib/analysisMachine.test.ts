import { describe, expect, it } from 'vitest';
import { AppError } from './errors';
import {
  analysisReducer,
  initialAnalysisState,
  statusMessage,
  type AnalysisState,
} from './analysisMachine';
import type { AnalysisResult, ExtractResponse } from './schema';

const file = new File(['%PDF-1.4'], 'demo.pdf', { type: 'application/pdf' });

const extraction = {
  extractionId: 'id-1',
  fileName: 'demo.pdf',
  pages: 1,
  chars: 10,
  pageInfo: [{ page: 1, method: 'text', chars: 10, confidence: null }],
  warnings: [],
  expiresAt: '2026-10-29T18:15:00Z',
} as ExtractResponse;

const result = {
  document: {
    fileName: 'demo.pdf',
    pages: 1,
    language: 'pl',
    type: 'umowa',
    title: 'Umowa demo',
    date: null,
  },
} as AnalysisResult;

function running(overrides: Partial<AnalysisState> = {}): AnalysisState {
  return {
    ...initialAnalysisState,
    phase: 'running',
    file,
    startedAt: 1_000,
    ...overrides,
  };
}

describe('analysisReducer', () => {
  it('startuje od kroku wgrywania z wybranym plikiem', () => {
    const next = analysisReducer(initialAnalysisState, {
      type: 'start',
      file,
      startedAt: 42,
    });
    expect(next).toMatchObject({
      phase: 'running',
      step: 0,
      file,
      startedAt: 42,
      result: null,
      error: null,
    });
  });

  it('zapisuje ekstrakcję i wynik, a po błędzie ustawia failedStep', () => {
    let state = running();
    state = analysisReducer(state, { type: 'set_step', step: 1 });
    state = analysisReducer(state, { type: 'extraction_ok', extraction });
    expect(state.extraction).toEqual(extraction);

    state = analysisReducer(state, { type: 'set_step', step: 2 });
    const failed = analysisReducer(state, {
      type: 'fail',
      error: new AppError('AI_UNAVAILABLE'),
      failedStep: 2,
    });
    expect(failed.phase).toBe('error');
    expect(failed.failedStep).toBe(2);
    expect(failed.step).toBe(2);
    expect(failed.extraction).toEqual(extraction);

    const done = analysisReducer(running({ extraction }), { type: 'done', result });
    expect(done).toMatchObject({ phase: 'done', step: 3, result });
  });

  it('anulowanie i reset wracają do stanu początkowego', () => {
    const state = running({ extraction, step: 2 });
    expect(analysisReducer(state, { type: 'abort' })).toEqual(initialAnalysisState);
    expect(analysisReducer(state, { type: 'reset' })).toEqual(initialAnalysisState);
  });

  it('retry od analizy zachowuje ekstrakcję, a od odczytu ją czyści', () => {
    const errored: AnalysisState = {
      ...running({ extraction, step: 2 }),
      phase: 'error',
      error: new AppError('AI_UNAVAILABLE'),
      failedStep: 2,
    };
    const retryAnalyze = analysisReducer(errored, {
      type: 'retry',
      fromStep: 2,
      startedAt: 99,
    });
    expect(retryAnalyze).toMatchObject({
      phase: 'running',
      step: 2,
      extraction,
      error: null,
      startedAt: 99,
    });

    const retryExtract = analysisReducer(errored, {
      type: 'retry',
      fromStep: 1,
      startedAt: 100,
    });
    expect(retryExtract.extraction).toBeNull();
    expect(retryExtract.step).toBe(1);
  });

  it('ignoruje przejścia poza fazą running', () => {
    const idle = analysisReducer(initialAnalysisState, { type: 'set_step', step: 2 });
    expect(idle).toEqual(initialAnalysisState);

    const errored: AnalysisState = {
      ...running(),
      phase: 'error',
      error: new AppError('NETWORK'),
      failedStep: 1,
    };
    expect(analysisReducer(errored, { type: 'done', result })).toEqual(errored);
  });
});

describe('statusMessage', () => {
  it('opisuje fazę po polsku', () => {
    expect(statusMessage(initialAnalysisState)).toMatch(/Gotowy/);
    expect(statusMessage(running({ step: 1 }))).toBe('Trwa: Odczyt tekstu');
    expect(
      statusMessage({
        ...running(),
        phase: 'error',
        error: new AppError('NETWORK'),
        failedStep: 1,
      }),
    ).toMatch(/Brak połączenia/);
    expect(
      statusMessage({
        ...running(),
        phase: 'done',
        step: 3,
        result,
      }),
    ).toBe('Analiza zakończona: Umowa demo');
  });
});
