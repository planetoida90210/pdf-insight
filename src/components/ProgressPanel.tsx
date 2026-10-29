import { useEffect, useState } from 'react';
import { formatSeconds } from '../lib/format';
import type { RunStep } from '../lib/analysisMachine';
import { StepOverview } from './StepOverview';

type ProgressPanelProps = {
  step: RunStep;
  statusText: string;
  startedAt: number;
  fileName: string;
  onCancel: () => void;
};

export function ProgressPanel({
  step,
  statusText,
  startedAt,
  fileName,
  onCancel,
}: ProgressPanelProps) {
  const [now, setNow] = useState(startedAt);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(id);
  }, []);

  return (
    <section className="panel progress" aria-labelledby="progress-heading">
      <span className="panel__numeral" aria-hidden="true">
        02
      </span>
      <p className="eyebrow">Przetwarzanie</p>
      <h2 id="progress-heading" className="section-title">
        Analiza w toku
      </h2>
      <p className="lede">Plik: {fileName}</p>
      <StepOverview
        activeStep={step}
        completedThrough={step > 0 ? ((step - 1) as RunStep) : null}
      />
      <div className="progress__meta">
        <p className="progress__status">{statusText}</p>
        <p className="progress__time">Czas: {formatSeconds(now - startedAt)}</p>
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          Anuluj
        </button>
      </div>
    </section>
  );
}
