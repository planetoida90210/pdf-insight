import { analyzeExtraction, extractText } from '../api/client';
import { AppError } from './errors';
import { documentTitle } from './format';
import { validatePdf } from './pdf';
import type { AnalysisResult, ExtractResponse } from './schema';

export const PIPELINE_STEPS = ['Wgranie PDF', 'Odczyt tekstu', 'Analiza AI', 'Wynik'] as const;

// The step a run is on or stopped at. A retry starts from this step.
export type RunStep = 0 | 1 | 2;

export type Run = { file: File; step: RunStep; extraction: ExtractResponse | null };

export type AnalysisState =
  | { phase: 'idle' }
  | ({ phase: 'running'; startedAt: number } & Run)
  | ({ phase: 'error'; error: AppError } & Run)
  | { phase: 'done'; file: File; result: AnalysisResult };

export type AnalysisAction =
  | { type: 'start'; run: Run; startedAt: number }
  | { type: 'extracting' }
  | { type: 'analyzing'; extraction: ExtractResponse }
  | { type: 'done'; result: AnalysisResult }
  | { type: 'fail'; error: AppError }
  | { type: 'reset' };

export const IDLE: AnalysisState = { phase: 'idle' };

export function analysisReducer(state: AnalysisState, action: AnalysisAction): AnalysisState {
  if (action.type === 'reset') return IDLE;
  if (action.type === 'start') {
    return { phase: 'running', startedAt: action.startedAt, ...action.run };
  }
  if (state.phase !== 'running') return state;
  switch (action.type) {
    case 'extracting':
      return { ...state, step: 1, extraction: null };
    case 'analyzing':
      return { ...state, step: 2, extraction: action.extraction };
    case 'done':
      return { phase: 'done', file: state.file, result: action.result };
    case 'fail': {
      const { file, step, extraction } = state;
      return { phase: 'error', file, step, extraction, error: action.error };
    }
  }
}

// Validation, text extraction, analysis. Returns the result, or null after an error or a cancel.
export async function runPipeline(
  run: Run,
  signal: AbortSignal,
  dispatch: (action: AnalysisAction) => void,
): Promise<AnalysisResult | null> {
  // An aborted run (cancel or a new file) must not change the state any more.
  const update = (action: AnalysisAction) => {
    if (!signal.aborted) dispatch(action);
  };
  const extract = () => {
    update({ type: 'extracting' });
    return extractText(run.file, signal);
  };
  const analyze = (extraction: ExtractResponse) => {
    update({ type: 'analyzing', extraction });
    return analyzeExtraction(extraction.extractionId, signal);
  };

  update({ type: 'start', run, startedAt: Date.now() });
  try {
    if (run.step === 0) await validatePdf(run.file);
    const extraction = run.extraction ?? (await extract());
    const result = await analyze(extraction).catch(async (error: unknown) => {
      if (!(error instanceof AppError && error.code === 'EXTRACTION_NOT_FOUND')) throw error;
      // The text expired in the server's memory, so the file is sent again, once.
      return analyze(await extract());
    });
    update({ type: 'done', result });
    return signal.aborted ? null : result;
  } catch (error) {
    update({ type: 'fail', error: error instanceof AppError ? error : new AppError('INTERNAL') });
    return null;
  }
}

export function statusMessage(state: AnalysisState): string {
  switch (state.phase) {
    case 'idle':
      return 'Wybierz plik PDF.';
    case 'running':
      return `Trwa: ${PIPELINE_STEPS[state.step]}`;
    case 'error':
      return state.error.message;
    case 'done':
      return `Analiza zakończona: ${documentTitle(state.result)}`;
  }
}
