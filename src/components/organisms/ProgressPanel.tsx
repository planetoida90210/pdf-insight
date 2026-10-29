import { useEffect, useState } from 'react';
import type { OcrProgress, RunStep } from '../../lib/analysisMachine';
import { formatOcrProgress, formatSeconds } from '../../lib/format';
import { Button } from '../atoms/Button';
import { Panel } from '../molecules/Panel';
import { StepList } from '../molecules/StepList';

const TICK_MS = 100;

type ProgressPanelProps = {
  fileName: string;
  step: RunStep;
  ocr: OcrProgress | null;
  startedAt: number;
  onCancel: () => void;
};

export function ProgressPanel({ fileName, step, ocr, startedAt, onCancel }: ProgressPanelProps) {
  const [now, setNow] = useState(startedAt);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  return (
    <Panel title={fileName}>
      <StepList current={step} detail={ocr ? formatOcrProgress(ocr) : undefined} />
      <p className="muted">{formatSeconds(now - startedAt)}</p>
      <Button onClick={onCancel}>Anuluj</Button>
    </Panel>
  );
}
