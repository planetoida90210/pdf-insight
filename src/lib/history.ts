import { z } from 'zod';
import { analysisResultSchema, type AnalysisResult } from './schema';

const STORAGE_KEY = 'pdf-insight:history';
export const HISTORY_LIMIT = 20;

const entrySchema = z.object({
  id: z.string().min(1),
  savedAt: z.iso.datetime({ offset: true }),
  result: analysisResultSchema,
});

export type HistoryEntry = z.infer<typeof entrySchema>;

// localStorage może rzucić wyjątek (tryb prywatny, zablokowane ciasteczka) albo zawierać śmieci,
// dlatego każdy wpis jest walidowany osobno, a uszkodzone są pomijane.
export function readHistory(): HistoryEntry[] {
  let raw: string | null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    return [];
  }
  if (raw === null) return [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];

  return parsed.flatMap((item: unknown) => {
    const entry = entrySchema.safeParse(item);
    return entry.success ? [entry.data] : [];
  });
}

// Przy przekroczeniu limitu miejsca usuwa najstarsze wpisy, aż zapis się zmieści.
function writeHistory(entries: HistoryEntry[]): HistoryEntry[] {
  for (let count = entries.length; count > 0; count--) {
    const kept = entries.slice(0, count);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(kept));
      return kept;
    } catch {
      // brak miejsca albo dostępu: próbujemy z mniejszą liczbą wpisów
    }
  }
  clearHistory();
  return [];
}

export function addToHistory(result: AnalysisResult): HistoryEntry[] {
  const entry: HistoryEntry = {
    id: crypto.randomUUID(),
    savedAt: new Date().toISOString(),
    result,
  };
  return writeHistory([entry, ...readHistory()].slice(0, HISTORY_LIMIT));
}

export function removeFromHistory(id: string): HistoryEntry[] {
  return writeHistory(readHistory().filter((entry) => entry.id !== id));
}

export function clearHistory(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // brak dostępu do localStorage: nie ma czego czyścić
  }
}
