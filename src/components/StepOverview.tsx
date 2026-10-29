import { PIPELINE_STEPS, type RunStep } from '../lib/analysisMachine';

type StepOverviewProps = {
  activeStep?: RunStep | null;
  completedThrough?: RunStep | null;
  compact?: boolean;
};

export function StepOverview({
  activeStep = null,
  completedThrough = null,
  compact = false,
}: StepOverviewProps) {
  return (
    <ol className={compact ? 'step-grid step-grid--compact' : 'step-grid'}>
      {PIPELINE_STEPS.map((label, index) => {
        const step = index as RunStep;
        const active = activeStep === step;
        const done = completedThrough !== null && step <= completedThrough && !active;
        return (
          <li
            key={label}
            className="step-card"
            data-active={active ? 'true' : 'false'}
            data-done={done ? 'true' : 'false'}
            aria-current={active ? 'step' : undefined}
          >
            <p className="step-card__index">Krok 0{index + 1}</p>
            <p className="step-card__label">{label}</p>
          </li>
        );
      })}
    </ol>
  );
}
