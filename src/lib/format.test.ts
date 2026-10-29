import { describe, expect, it } from 'vitest';
import { insightFileName } from './download';
import { formatAmount, formatDate, formatFileSize, formatSeconds, languageName } from './format';

// Intl używa twardych spacji jako separatora tysięcy, w testach porównujemy zwykłe spacje.
const plain = (text: string) => text.replace(/\s/g, ' ');

describe('format', () => {
  it('formatuje kwoty po polsku z walutą', () => {
    expect(plain(formatAmount(184500, 'PLN'))).toBe('184 500,00 zł');
    expect(plain(formatAmount(8600, 'EUR'))).toBe('8600,00 €');
    expect(plain(formatAmount(890, 'USD'))).toBe('890,00 USD');
  });

  it('formatuje daty ISO bez przesunięcia strefy czasowej', () => {
    expect(formatDate('2026-03-12')).toBe('12 marca 2026');
    expect(formatDate('2026-01-01')).toBe('1 stycznia 2026');
  });

  it('formatuje rozmiar pliku i czas', () => {
    expect(plain(formatFileSize(512 * 1024))).toBe('512 KB');
    expect(plain(formatFileSize(2.5 * 1024 * 1024))).toBe('2,5 MB');
    expect(formatSeconds(8421)).toBe('8,4 s');
  });

  it('podaje nazwę języka po polsku', () => {
    expect(languageName('pl')).toBe('polski');
    expect(languageName('en')).toBe('angielski');
  });

  it('tworzy nazwę pliku z wynikiem', () => {
    expect(insightFileName('umowa.pdf')).toBe('umowa.insight.json');
    expect(insightFileName('Raport.Q3.PDF')).toBe('Raport.Q3.insight.json');
  });
});
