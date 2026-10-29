import type { AnalysisResult } from './schema';

export type PageBadge = 'ocr' | 'vision' | 'hidden';

export function badgesForPage(result: AnalysisResult, page: number): PageBadge[] {
  const badges: PageBadge[] = [];
  if (result.meta.ocrPages.includes(page)) badges.push('ocr');
  if (result.warnings.some((w) => w.code === 'VISION_USED' && w.page === page)) {
    badges.push('vision');
  }
  if (result.meta.hiddenTextPages.includes(page)) badges.push('hidden');
  return badges;
}

export const PAGE_BADGE_LABELS: Record<PageBadge, string> = {
  ocr: 'OCR',
  vision: 'Vision',
  hidden: 'Ukryty tekst',
};
