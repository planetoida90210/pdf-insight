import type { AnalysisResult } from './schema';

export const PAGE_BADGES = {
  ocr: { label: 'OCR', tone: 'accent' },
  vision: { label: 'OCR AI', tone: 'accent' },
  hidden: { label: 'Ukryty tekst', tone: 'warn' },
} as const;

export type PageBadge = keyof typeof PAGE_BADGES;

export function badgesForPage(result: AnalysisResult, page: number): PageBadge[] {
  const badges: PageBadge[] = [];
  if (result.meta.ocrPages.includes(page)) badges.push('ocr');
  if (result.warnings.some((w) => w.code === 'VISION_USED' && w.page === page)) {
    badges.push('vision');
  }
  if (result.meta.hiddenTextPages.includes(page)) badges.push('hidden');
  return badges;
}

export function pageElementId(page: number): string {
  return `page-${page}`;
}

// The scroll uses CSS scroll-behavior, so it respects prefers-reduced-motion.
export function focusPage(page: number): void {
  const element = document.getElementById(pageElementId(page));
  element?.scrollIntoView({ block: 'center' });
  element?.focus({ preventScroll: true });
}
