import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useAnalysis } from '../hooks/useAnalysis';
import {
  addToHistory,
  clearHistory,
  readHistory,
  removeFromHistory,
  type HistoryEntry,
} from '../lib/history';
import type { AnalysisResult } from '../lib/schema';
import { EmptyState } from './EmptyState';
import { ErrorPanel } from './ErrorPanel';
import { Footer } from './Footer';
import { Header } from './Header';
import { HistoryPanel } from './HistoryPanel';
import { ProgressPanel } from './ProgressPanel';
import { ResultsView } from './ResultsView';

export function App() {
  const { state, elapsedMs, providerLabel, statusText, start, retry, cancel, reset } =
    useAnalysis();
  const [history, setHistory] = useState<HistoryEntry[]>(() => readHistory());
  const [historyView, setHistoryView] = useState<{
    result: AnalysisResult;
  } | null>(null);
  const savedResultRef = useRef<AnalysisResult | null>(null);

  useEffect(() => {
    if (state.phase !== 'done' || !state.result) return;
    if (savedResultRef.current === state.result) return;
    savedResultRef.current = state.result;
    setHistory(addToHistory(state.result));
    setHistoryView(null);
  }, [state.phase, state.result]);

  const onReset = () => {
    savedResultRef.current = null;
    setHistoryView(null);
    reset();
  };

  const onOpenHistory = (entry: HistoryEntry) => {
    savedResultRef.current = null;
    reset();
    setHistoryView({ result: entry.result });
  };

  const showHistoryList = state.phase === 'idle' && historyView === null;

  let main: ReactNode;
  if (historyView) {
    main = <ResultsView result={historyView.result} file={null} onReset={onReset} />;
  } else if (state.phase === 'running' && state.file) {
    main = (
      <ProgressPanel
        step={state.step}
        statusText={statusText}
        elapsedMs={elapsedMs}
        fileName={state.file.name}
        onCancel={cancel}
      />
    );
  } else if (state.phase === 'error' && state.error) {
    main = <ErrorPanel error={state.error} onRetry={retry} onChooseAnother={onReset} />;
  } else if (state.phase === 'done' && state.result) {
    main = <ResultsView result={state.result} file={state.file} onReset={onReset} />;
  } else {
    main = <EmptyState providerLabel={providerLabel} onFile={start} />;
  }

  return (
    <div className="app-shell">
      <Header />
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {statusText}
      </div>
      {main}
      {showHistoryList ? (
        <HistoryPanel
          entries={history}
          onOpen={onOpenHistory}
          onDelete={(id) => setHistory(removeFromHistory(id))}
          onClear={() => {
            clearHistory();
            setHistory([]);
          }}
        />
      ) : null}
      <Footer />
    </div>
  );
}
