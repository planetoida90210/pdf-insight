import { useRef } from 'react';
import { DOCUMENT_TYPE_LABELS, formatDateTime } from '../../lib/format';
import type { HistoryEntry } from '../../lib/history';
import { Button } from '../atoms/Button';
import { Panel } from '../molecules/Panel';

type HistoryPanelProps = {
  entries: HistoryEntry[];
  onOpen: (entry: HistoryEntry) => void;
  onDelete: (id: string) => void;
  onClear: () => void;
};

export function HistoryPanel({ entries, onOpen, onDelete, onClear }: HistoryPanelProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Usunięty przycisk zabrałby fokus ze sobą, więc fokus wraca na nagłówek historii.
  const focusHeading = () => headingRef.current?.focus();

  return (
    <Panel title="Historia" headingRef={headingRef}>
      {entries.length === 0 ? (
        <p className="muted">Brak analiz</p>
      ) : (
        <>
          <ul className="history">
            {entries.map((entry) => {
              const { fileName, type } = entry.result.document;
              return (
                <li key={entry.id} className="row">
                  <div>
                    <p>{fileName}</p>
                    <p className="muted">
                      {DOCUMENT_TYPE_LABELS[type]}, {formatDateTime(entry.savedAt)}
                    </p>
                  </div>
                  <div className="row">
                    <Button aria-label={`Otwórz ${fileName}`} onClick={() => onOpen(entry)}>
                      Otwórz
                    </Button>
                    <Button
                      aria-label={`Usuń ${fileName}`}
                      onClick={() => {
                        onDelete(entry.id);
                        focusHeading();
                      }}
                    >
                      Usuń
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
          <Button
            onClick={() => {
              onClear();
              focusHeading();
            }}
          >
            Wyczyść historię
          </Button>
        </>
      )}
    </Panel>
  );
}
