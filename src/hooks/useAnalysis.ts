import { useEffect, useReducer, useRef } from 'react';
import { analysisReducer, IDLE, runPipeline, type Run } from '../lib/analysisMachine';
import type { AnalysisResult } from '../lib/schema';

export function useAnalysis(onResult: (result: AnalysisResult) => void) {
  const [state, dispatch] = useReducer(analysisReducer, IDLE);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function run(next: Run) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const result = await runPipeline(next, controller.signal, dispatch);
    if (result) onResult(result);
  }

  function start(file: File) {
    void run({ file, step: 0, extraction: null });
  }

  // Ponawia tylko krok, który się nie udał. Po błędzie analizy zachowany odczyt tekstu jest użyty ponownie.
  function retry() {
    if (state.phase !== 'error') return;
    void run({ file: state.file, step: state.step, extraction: state.extraction });
  }

  function reset() {
    controllerRef.current?.abort();
    dispatch({ type: 'reset' });
  }

  return { state, start, retry, reset };
}
