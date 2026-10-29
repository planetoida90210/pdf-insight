import { DOCUMENT_TYPE_LABELS, formatDateTime } from '../lib/format';
import type { HistoryEntry } from '../lib/history';

type HistoryPanelProps = {
  entries: HistoryEntry[];
  onOpen: (entry: HistoryEntry) => void;
  onDelete: (id: string) => void;
  onClear: () => void;
};

export function HistoryPanel({ entries, onOpen, onDelete, onClear }: HistoryPanelProps) {
  return (
    <section className="history" aria-labelledby="history-heading">
      <div className="history__header">
        <h2 id="history-heading">Historia analiz</h2>
        {entries.length > 0 ? (
          <button type="button" className="btn btn--danger" onClick={onClear}>
            Wyczyść historię
          </button>
        ) : null}
      </div>

      {entries.length === 0 ? (
        <p className="history__empty">
          Brak zapisanych analiz. Wyniki pojawią się tu po pierwszej analizie.
        </p>
      ) : (
        <ul className="history__list">
          {entries.map((entry) => (
            <li key={entry.id} className="history__item">
              <div className="history__meta">
                <p className="history__name">{entry.result.document.fileName}</p>
                <p className="history__sub">
                  {DOCUMENT_TYPE_LABELS[entry.result.document.type]} ·{' '}
                  {formatDateTime(entry.savedAt)}
                </p>
              </div>
              <div className="history__actions">
                <button type="button" className="btn btn--primary" onClick={() => onOpen(entry)}>
                  Otwórz
                </button>
                <button type="button" className="btn btn--ghost" onClick={() => onDelete(entry.id)}>
                  Usuń
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
