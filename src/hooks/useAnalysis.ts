import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import {
  analyzeExtraction,
  extractText,
  FALLBACK_PROVIDER_LABEL,
  fetchHealth,
  PROVIDER_LABELS,
} from '../api/client';
import {
  analysisReducer,
  initialAnalysisState,
  statusMessage,
  type AnalysisState,
  type PipelineStepIndex,
} from '../lib/analysisMachine';
import { AppError } from '../lib/errors';
import { validatePdf } from '../lib/pdf';
import type { ExtractResponse } from '../lib/schema';

function isAbort(error: unknown, signal: AbortSignal): boolean {
  return signal.aborted || (error instanceof AppError && error.code === 'ABORTED');
}

export function useAnalysis() {
  const [state, dispatch] = useReducer(analysisReducer, initialAnalysisState);
  const [now, setNow] = useState(() => Date.now());
  const [providerLabel, setProviderLabel] = useState(FALLBACK_PROVIDER_LABEL);
  const controllerRef = useRef<AbortController | null>(null);
  const stateRef = useRef<AnalysisState>(initialAnalysisState);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchHealth(controller.signal).then((health) => {
      if (health) setProviderLabel(PROVIDER_LABELS[health.provider]);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (state.phase !== 'running' || state.startedAt === null) return;
    const tick = () => setNow(Date.now());
    const timeout = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, 200);
    return () => {
      window.clearTimeout(timeout);
      window.clearInterval(id);
    };
  }, [state.phase, state.startedAt]);

  const elapsedMs =
    state.phase === 'running' && state.startedAt !== null ? Math.max(0, now - state.startedAt) : 0;

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    dispatch({ type: 'abort' });
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  const runPipeline = useCallback(async (file: File, fromStep: PipelineStepIndex) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const { signal } = controller;
    const startedAt = Date.now();

    // Retry od kroku analizy ponownie używa zapisanej odpowiedzi extract.
    let extraction: ExtractResponse | null = fromStep >= 2 ? stateRef.current.extraction : null;
    let activeStep: PipelineStepIndex = fromStep;

    if (fromStep === 0) {
      dispatch({ type: 'start', file, startedAt });
    } else {
      dispatch({ type: 'retry', fromStep, startedAt });
    }

    const abortToIdle = () => {
      dispatch({ type: 'abort' });
    };

    const fail = (error: unknown) => {
      if (isAbort(error, signal)) {
        abortToIdle();
        return;
      }
      const appError = error instanceof AppError ? error : new AppError('INTERNAL');
      dispatch({ type: 'fail', error: appError, failedStep: activeStep });
    };

    try {
      if (fromStep <= 0) {
        activeStep = 0;
        dispatch({ type: 'set_step', step: 0 });
        await validatePdf(file);
        if (signal.aborted) return abortToIdle();
      }

      if (fromStep <= 1) {
        activeStep = 1;
        dispatch({ type: 'set_step', step: 1 });
        extraction = await extractText(file, signal);
        if (signal.aborted) return abortToIdle();
        dispatch({ type: 'extraction_ok', extraction });
      }

      if (!extraction) {
        activeStep = 2;
        fail(new AppError('INTERNAL'));
        return;
      }

      activeStep = 2;
      dispatch({ type: 'set_step', step: 2 });

      try {
        const result = await analyzeExtraction(extraction.extractionId, signal);
        if (signal.aborted) return abortToIdle();
        dispatch({ type: 'done', result });
      } catch (error) {
        if (isAbort(error, signal)) return abortToIdle();

        if (error instanceof AppError && error.code === 'EXTRACTION_NOT_FOUND') {
          activeStep = 1;
          dispatch({ type: 'set_step', step: 1 });
          extraction = await extractText(file, signal);
          if (signal.aborted) return abortToIdle();
          dispatch({ type: 'extraction_ok', extraction });

          activeStep = 2;
          dispatch({ type: 'set_step', step: 2 });
          const result = await analyzeExtraction(extraction.extractionId, signal);
          if (signal.aborted) return abortToIdle();
          dispatch({ type: 'done', result });
          return;
        }

        fail(error);
      }
    } catch (error) {
      fail(error);
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  const start = useCallback(
    (file: File) => {
      void runPipeline(file, 0);
    },
    [runPipeline],
  );

  const retry = useCallback(() => {
    const current = stateRef.current;
    if (!current.file || current.failedStep === null) return;
    void runPipeline(current.file, current.failedStep);
  }, [runPipeline]);

  return {
    state,
    elapsedMs,
    providerLabel,
    statusText: statusMessage(state),
    start,
    retry,
    cancel,
    reset,
  };
}
