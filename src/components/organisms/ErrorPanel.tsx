import type { AppError } from '../../lib/errors';
import { Button } from '../atoms/Button';
import { Panel } from '../molecules/Panel';

type ErrorPanelProps = {
  error: AppError;
  onRetry: () => void;
  onReset: () => void;
};

export function ErrorPanel({ error, onRetry, onReset }: ErrorPanelProps) {
  return (
    <Panel title={error.message}>
      <div className="row">
        {error.retryable ? (
          <Button variant="primary" onClick={onRetry}>
            Spróbuj ponownie
          </Button>
        ) : null}
        <Button onClick={onReset}>Wybierz inny plik</Button>
      </div>
    </Panel>
  );
}
