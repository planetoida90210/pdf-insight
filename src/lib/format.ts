import type { AnalysisResult, DocumentType } from './schema';

const LOCALE = 'pl-PL';

export const EMPTY_TEXT = 'Brak';

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  faktura: 'Faktura',
  umowa: 'Umowa',
  oferta: 'Oferta',
  raport: 'Raport',
  inne: 'Inny dokument',
};

export function documentTitle(result: AnalysisResult): string {
  return result.document.title ?? result.document.fileName;
}

export function formatAmount(value: number, currency: string): string {
  return new Intl.NumberFormat(LOCALE, { style: 'currency', currency }).format(value);
}

// Daty z wyniku to dni kalendarzowe bez strefy, więc formatujemy je w UTC, żeby nie przesunęły się o dzień.
export function formatDate(isoDate: string): string {
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'long', timeZone: 'UTC' }).format(
    new Date(`${isoDate}T00:00:00Z`),
  );
}

export function formatDateTime(isoDateTime: string): string {
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(isoDateTime),
  );
}

export function formatSeconds(ms: number): string {
  return `${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(ms / 1000)} s`;
}

const languageNames = new Intl.DisplayNames([LOCALE], { type: 'language' });

export function languageName(code: string): string {
  return languageNames.of(code) ?? code;
}
