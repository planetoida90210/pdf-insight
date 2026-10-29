import { describe, expect, it } from 'vitest';
import umowa from '../../schema/fixtures/valid/umowa.json';
import { analysisResultSchema } from './schema';
import { badgesForPage } from './pageBadges';

const result = analysisResultSchema.parse(umowa);

describe('badgesForPage', () => {
  it('marks OCR and hidden-text pages from meta', () => {
    expect(badgesForPage(result, 11)).toEqual(['ocr']);
    expect(badgesForPage(result, 4)).toEqual(['hidden']);
    expect(badgesForPage(result, 1)).toEqual([]);
  });

  it('adds vision badge from warnings', () => {
    const withVision = analysisResultSchema.parse({
      ...result,
      warnings: [
        ...result.warnings,
        { code: 'VISION_USED', page: 11, message: 'Transkrypcja wizyjna strony 11.' },
      ],
    });
    expect(badgesForPage(withVision, 11)).toEqual(['ocr', 'vision']);
  });
});
