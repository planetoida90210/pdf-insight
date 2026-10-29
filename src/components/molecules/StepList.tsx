import { PIPELINE_STEPS } from '../../lib/analysisMachine';

type StepListProps = {
  current?: number;
};

export function StepList({ current }: StepListProps) {
  return (
    <ol className="steps">
      {PIPELINE_STEPS.map((label, index) => (
        <li
          key={label}
          data-done={current !== undefined && index < current}
          aria-current={index === current ? 'step' : undefined}
        >
          {label}
        </li>
      ))}
    </ol>
  );
}
