import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import umowa from '../../schema/fixtures/valid/umowa.json';
import {
  addToHistory,
  clearHistory,
  HISTORY_LIMIT,
  readHistory,
  removeFromHistory,
} from './history';
import { analysisResultSchema, type AnalysisResult } from './schema';

const KEY = 'pdf-insight:history';
const result: AnalysisResult = analysisResultSchema.parse(umowa);

class MemoryStorage {
  items = new Map<string, string>();
  quota = Infinity;

  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (value.length > this.quota) throw new DOMException('Quota exceeded', 'QuotaExceededError');
    this.items.set(key, value);
  }

  removeItem(key: string): void {
    this.items.delete(key);
  }
}

let storage: MemoryStorage;

beforeEach(() => {
  storage = new MemoryStorage();
  vi.stubGlobal('localStorage', storage);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function withFileName(fileName: string): AnalysisResult {
  return { ...result, document: { ...result.document, fileName } };
}

describe('history', () => {
  it('is empty when nothing is stored', () => {
    expect(readHistory()).toEqual([]);
  });

  it('puts the newest result first', () => {
    addToHistory(withFileName('a.pdf'));
    addToHistory(withFileName('b.pdf'));
    expect(readHistory().map((entry) => entry.result.document.fileName)).toEqual([
      'b.pdf',
      'a.pdf',
    ]);
  });

  it(`keeps at most ${HISTORY_LIMIT} results`, () => {
    for (let i = 0; i < HISTORY_LIMIT + 5; i++) addToHistory(withFileName(`${i}.pdf`));
    const entries = readHistory();
    expect(entries).toHaveLength(HISTORY_LIMIT);
    expect(entries[0]?.result.document.fileName).toBe(`${HISTORY_LIMIT + 4}.pdf`);
  });

  it('removes one entry and clears all', () => {
    addToHistory(withFileName('a.pdf'));
    const [newest] = addToHistory(withFileName('b.pdf'));
    expect(removeFromHistory(newest?.id ?? '').map((e) => e.result.document.fileName)).toEqual([
      'a.pdf',
    ]);
    clearHistory();
    expect(readHistory()).toEqual([]);
  });

  it('skips broken entries and invalid JSON', () => {
    const [valid] = addToHistory(result);
    storage.setItem(KEY, JSON.stringify([valid, { id: 'x', savedAt: 'yesterday', result: {} }]));
    expect(readHistory()).toEqual([valid]);

    storage.setItem(KEY, '{not json');
    expect(readHistory()).toEqual([]);

    storage.setItem(KEY, JSON.stringify({ not: 'array' }));
    expect(readHistory()).toEqual([]);
  });

  it('drops the oldest entries when out of space', () => {
    addToHistory(withFileName('a.pdf'));
    addToHistory(withFileName('b.pdf'));
    storage.quota = (storage.getItem(KEY) ?? '').length;

    const entries = addToHistory(withFileName('c.pdf'));
    expect(entries.map((e) => e.result.document.fileName)).toEqual(['c.pdf', 'b.pdf']);
    expect(readHistory()).toEqual(entries);
  });

  it('does not throw when localStorage is blocked', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new DOMException('Blocked', 'SecurityError');
      },
      setItem: () => {
        throw new DOMException('Blocked', 'SecurityError');
      },
      removeItem: () => {
        throw new DOMException('Blocked', 'SecurityError');
      },
    });
    expect(readHistory()).toEqual([]);
    expect(addToHistory(result)).toEqual([]);
    expect(() => clearHistory()).not.toThrow();
  });
});
