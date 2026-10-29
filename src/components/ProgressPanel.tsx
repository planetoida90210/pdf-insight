import { formatSeconds } from '../lib/format';
import type { PipelineStepIndex } from '../lib/analysisMachine';
import { StepOverview } from './StepOverview';

type ProgressPanelProps = {
  step: PipelineStepIndex;
  statusText: string;
  elapsedMs: number;
  fileName: string;
  onCancel: () => void;
};

export function ProgressPanel({
  step,
  statusText,
  elapsedMs,
  fileName,
  onCancel,
}: ProgressPanelProps) {
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
        completedThrough={step > 0 ? ((step - 1) as PipelineStepIndex) : null}
      />
      <div className="progress__meta">
        <p className="progress__status">{statusText}</p>
        <p className="progress__time">Czas: {formatSeconds(elapsedMs)}</p>
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          Anuluj
        </button>
      </div>
    </section>
  );
}
