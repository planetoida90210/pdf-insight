import type { AppError } from './errors';
import type { AnalysisResult, ExtractResponse } from './schema';

export const PIPELINE_STEPS = ['Wgranie PDF', 'Odczyt tekstu', 'Analiza AI', 'Wynik'] as const;

export type PipelineStepIndex = 0 | 1 | 2 | 3;

export type AnalysisPhase = 'idle' | 'running' | 'error' | 'done';

export type AnalysisState = {
  phase: AnalysisPhase;
  step: PipelineStepIndex;
  file: File | null;
  extraction: ExtractResponse | null;
  result: AnalysisResult | null;
  error: AppError | null;
  failedStep: PipelineStepIndex | null;
  startedAt: number | null;
};

export type AnalysisAction =
  | { type: 'start'; file: File; startedAt: number }
  | { type: 'retry'; fromStep: PipelineStepIndex; startedAt: number }
  | { type: 'set_step'; step: PipelineStepIndex }
  | { type: 'extraction_ok'; extraction: ExtractResponse }
  | { type: 'done'; result: AnalysisResult }
  | { type: 'fail'; error: AppError; failedStep: PipelineStepIndex }
  | { type: 'reset' }
  | { type: 'abort' };

export const initialAnalysisState: AnalysisState = {
  phase: 'idle',
  step: 0,
  file: null,
  extraction: null,
  result: null,
  error: null,
  failedStep: null,
  startedAt: null,
};

export function analysisReducer(state: AnalysisState, action: AnalysisAction): AnalysisState {
  switch (action.type) {
    case 'start':
      return {
        ...initialAnalysisState,
        phase: 'running',
        step: 0,
        file: action.file,
        startedAt: action.startedAt,
      };
    case 'retry':
      if (!state.file) return state;
      return {
        ...state,
        phase: 'running',
        step: action.fromStep,
        result: null,
        error: null,
        failedStep: null,
        startedAt: action.startedAt,
        extraction: action.fromStep >= 2 ? state.extraction : null,
      };
    case 'set_step':
      if (state.phase !== 'running') return state;
      return { ...state, step: action.step };
    case 'extraction_ok':
      if (state.phase !== 'running') return state;
      return { ...state, extraction: action.extraction };
    case 'done':
      if (state.phase !== 'running') return state;
      return {
        ...state,
        phase: 'done',
        step: 3,
        result: action.result,
        error: null,
        failedStep: null,
      };
    case 'fail':
      if (state.phase !== 'running') return state;
      return {
        ...state,
        phase: 'error',
        error: action.error,
        failedStep: action.failedStep,
        step: action.failedStep,
      };
    case 'abort':
    case 'reset':
      return initialAnalysisState;
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

export function statusMessage(state: AnalysisState): string {
  if (state.phase === 'idle') return 'Gotowy do analizy. Wybierz plik PDF.';
  if (state.phase === 'error' && state.error) return state.error.message;
  if (state.phase === 'done' && state.result) {
    const title = state.result.document.title ?? state.result.document.fileName;
    return `Analiza zakończona: ${title}`;
  }
  return `Trwa: ${PIPELINE_STEPS[state.step]}`;
}
