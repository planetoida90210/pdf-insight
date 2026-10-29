import { PIPELINE_STEPS } from '../../lib/analysisMachine';

type StepListProps = {
  current?: number;
  // Progress within the current step, shown next to its label.
  detail?: string;
};

export function StepList({ current, detail }: StepListProps) {
  return (
    <ol className="steps">
      {PIPELINE_STEPS.map((label, index) => (
        <li
          key={label}
          data-done={current !== undefined && index < current}
          aria-current={index === current ? 'step' : undefined}
        >
          {label}
          {index === current && detail && <span className="steps__detail">{detail}</span>}
        </li>
      ))}
    </ol>
  );
}
