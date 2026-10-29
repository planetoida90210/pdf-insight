import { describe, expect, it } from 'vitest';
import { insightFileName } from './download';

describe('insightFileName', () => {
  it('replaces the PDF extension', () => {
    expect(insightFileName('umowa 14-2026.PDF')).toBe('umowa 14-2026.insight.json');
    expect(insightFileName('Raport.Q3.pdf')).toBe('Raport.Q3.insight.json');
  });

  it('cannot leave the download folder or carry control characters', () => {
    expect(insightFileName('../..\\evil:\u0000name.pdf')).toBe('.._.._evil__name.insight.json');
  });

  it('cannot reorder how the name reads', () => {
    expect(insightFileName('raport\u202etxt.pdf')).toBe('raporttxt.insight.json');
  });
});
