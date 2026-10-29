import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FALLBACK_PROVIDER_LABEL, fetchHealth, PROVIDER_LABELS } from '../api/client';
import { useAnalysis } from '../hooks/useAnalysis';
import {
  addToHistory,
  clearHistory,
  readHistory,
  removeFromHistory,
  type HistoryEntry,
} from '../lib/history';
import { statusMessage, type AnalysisState } from '../lib/analysisMachine';
import type { AnalysisResult } from '../lib/schema';
import { EmptyState } from './EmptyState';
import { ErrorPanel } from './ErrorPanel';
import { Footer } from './Footer';
import { Header } from './Header';
import { HistoryPanel } from './HistoryPanel';
import { ProgressPanel } from './ProgressPanel';
import { ResultsView } from './ResultsView';

type MainView = 'empty' | 'progress' | 'error' | 'done' | 'history';

function mainViewOf(
  historyView: { result: AnalysisResult } | null,
  phase: AnalysisState['phase'],
): MainView {
  if (historyView) return 'history';
  if (phase === 'running') return 'progress';
  if (phase === 'error') return 'error';
  if (phase === 'done') return 'done';
  return 'empty';
}

const VIEW_HEADING: Record<MainView, string> = {
  empty: 'empty-heading',
  progress: 'progress-heading',
  error: 'error-heading',
  done: 'result-heading',
  history: 'result-heading',
};

function focusViewHeading(view: MainView): void {
  const el = document.getElementById(VIEW_HEADING[view]);
  if (!(el instanceof HTMLElement)) return;
  if (!el.hasAttribute('tabindex')) el.tabIndex = -1;
  el.focus({ preventScroll: true });
}

export function App() {
  const [history, setHistory] = useState<HistoryEntry[]>(() => readHistory());
  const [historyView, setHistoryView] = useState<{
    result: AnalysisResult;
  } | null>(null);
  const [providerLabel, setProviderLabel] = useState(FALLBACK_PROVIDER_LABEL);
  const { state, start, retry, reset } = useAnalysis((result) => setHistory(addToHistory(result)));
  const statusText = statusMessage(state);
  const viewRef = useRef<MainView | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void fetchHealth(controller.signal).then((provider) => {
      if (provider) setProviderLabel(PROVIDER_LABELS[provider]);
    });
    return () => controller.abort();
  }, []);

  const view = mainViewOf(historyView, state.phase);

  // Po zmianie widoku przenieś fokus na nagłówek panelu (klawiatura / czytniki).
  useEffect(() => {
    if (viewRef.current === null) {
      viewRef.current = view;
      return;
    }
    if (viewRef.current === view) return;
    viewRef.current = view;
    const id = window.requestAnimationFrame(() => focusViewHeading(view));
    return () => window.cancelAnimationFrame(id);
  }, [view]);

  const onReset = () => {
    setHistoryView(null);
    reset();
  };

  const onOpenHistory = (entry: HistoryEntry) => {
    reset();
    setHistoryView({ result: entry.result });
  };

  const showHistoryList = state.phase === 'idle' && historyView === null;

  let main: ReactNode;
  if (historyView) {
    main = <ResultsView result={historyView.result} file={null} onReset={onReset} />;
  } else if (state.phase === 'running') {
    main = (
      <ProgressPanel
        step={state.step}
        statusText={statusText}
        startedAt={state.startedAt}
        fileName={state.file.name}
        onCancel={reset}
      />
    );
  } else if (state.phase === 'error') {
    main = <ErrorPanel error={state.error} onRetry={retry} onChooseAnother={onReset} />;
  } else if (state.phase === 'done') {
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
