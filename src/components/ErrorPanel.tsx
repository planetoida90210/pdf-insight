import type { AppError } from '../lib/errors';

type ErrorPanelProps = {
  error: AppError;
  onRetry: () => void;
  onChooseAnother: () => void;
};

export function ErrorPanel({ error, onRetry, onChooseAnother }: ErrorPanelProps) {
  return (
    <section className="panel" aria-labelledby="error-heading" role="alert">
      <span className="panel__numeral" aria-hidden="true">
        !
      </span>
      <p className="eyebrow">Błąd</p>
      <h2 id="error-heading" className="section-title">
        Nie udało się dokończyć analizy
      </h2>
      <p className="error-panel__message">{error.message}</p>
      <div className="btn-row">
        {error.retryable ? (
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            Spróbuj ponownie
          </button>
        ) : null}
        <button type="button" className="btn btn--ghost" onClick={onChooseAnother}>
          Wybierz inny plik
        </button>
      </div>
    </section>
  );
}
