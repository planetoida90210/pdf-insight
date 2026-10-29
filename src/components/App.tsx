import { useEffect, useRef, useState } from 'react';
import { useAnalysis } from '../hooks/useAnalysis';
import { statusMessage } from '../lib/analysisMachine';
import { addToHistory, clearHistory, readHistory, removeFromHistory } from '../lib/history';
import type { AnalysisResult } from '../lib/schema';
import { ErrorPanel } from './organisms/ErrorPanel';
import { HistoryPanel } from './organisms/HistoryPanel';
import { ProgressPanel } from './organisms/ProgressPanel';
import { ResultsView } from './organisms/ResultsView';
import { UploadPanel } from './organisms/UploadPanel';

export function App() {
  const [history, setHistory] = useState(readHistory);
  const [opened, setOpened] = useState<AnalysisResult | null>(null);
  const { state, start, retry, reset } = useAnalysis((result) => setHistory(addToHistory(result)));
  const view = opened ? 'history' : state.phase;
  const lastView = useRef(view);
  const showUpload = !opened && state.phase === 'idle';

  // Po zmianie widoku fokus przechodzi na nagłówek nowego panelu, żeby klawiatura i czytnik ekranu nie zostały na usuniętym przycisku.
  useEffect(() => {
    if (lastView.current === view) return;
    lastView.current = view;
    document.querySelector<HTMLElement>('main h2')?.focus();
  }, [view]);

  const startOver = () => {
    setOpened(null);
    reset();
  };

  return (
    <>
      <header className="header">
        <h1>
          PDF <span>Insight</span>
        </h1>
      </header>
      <main className="main">
        {showUpload && <UploadPanel onFile={start} />}
        {state.phase === 'running' && (
          <ProgressPanel
            fileName={state.file.name}
            step={state.step}
            startedAt={state.startedAt}
            onCancel={startOver}
          />
        )}
        {state.phase === 'error' && (
          <ErrorPanel error={state.error} onRetry={retry} onReset={startOver} />
        )}
        {state.phase === 'done' && (
          <ResultsView result={state.result} file={state.file} onReset={startOver} />
        )}
        {opened && <ResultsView result={opened} file={null} onReset={startOver} />}
        {showUpload && (
          <HistoryPanel
            entries={history}
            onOpen={(entry) => setOpened(entry.result)}
            onDelete={(id) => setHistory(removeFromHistory(id))}
            onClear={() => {
              clearHistory();
              setHistory([]);
            }}
          />
        )}
      </main>
      <p className="sr-only" aria-live="polite">
        {statusMessage(state)}
      </p>
    </>
  );
}
