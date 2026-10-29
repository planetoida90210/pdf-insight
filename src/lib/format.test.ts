import { describe, expect, it } from 'vitest';
import { formatAmount, formatDate, formatOcrProgress, formatSeconds, languageName } from './format';

// Intl separates thousands with non-breaking spaces; the tests compare plain spaces.
const plain = (text: string) => text.replace(/\s/g, ' ');

describe('format', () => {
  it('formats amounts in Polish with the currency', () => {
    expect(plain(formatAmount(184500, 'PLN'))).toBe('184 500,00 zł');
    expect(plain(formatAmount(8600, 'EUR'))).toBe('8600,00 €');
    expect(plain(formatAmount(890, 'USD'))).toBe('890,00 USD');
  });

  it('formats ISO dates without a time zone shift', () => {
    expect(formatDate('2026-03-12')).toBe('12 marca 2026');
    expect(formatDate('2026-01-01')).toBe('1 stycznia 2026');
  });

  it('formats a duration', () => {
    expect(formatSeconds(8421)).toBe('8,4 s');
  });

  it('formats the OCR progress', () => {
    expect(formatOcrProgress({ done: 3, total: 10 })).toBe('OCR 3/10');
  });

  it('names the language in Polish', () => {
    expect(languageName('pl')).toBe('polski');
    expect(languageName('en')).toBe('angielski');
  });
});
