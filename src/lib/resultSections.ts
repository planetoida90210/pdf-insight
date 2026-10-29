import { DOCUMENT_TYPE_LABELS, EMPTY_TEXT, formatAmount, formatDate, languageName } from './format';
import type { AnalysisResult } from './schema';

// The blocks of the result view. Components only map these lists, so labels and order live here.

type Read<T> = (result: AnalysisResult) => T;

export const DOCUMENT_FIELDS: { label: string; value: Read<string> }[] = [
  { label: 'Typ', value: (r) => DOCUMENT_TYPE_LABELS[r.document.type] },
  { label: 'Język', value: (r) => languageName(r.document.language) },
  { label: 'Data', value: (r) => (r.document.date ? formatDate(r.document.date) : EMPTY_TEXT) },
  { label: 'Strony', value: (r) => String(r.document.pages) },
  { label: 'Plik', value: (r) => r.document.fileName },
];

export const LIST_SECTIONS: { title: string; items: Read<string[]>; inline?: boolean }[] = [
  { title: 'Kluczowe punkty', items: (r) => r.keyPoints },
  { title: 'Organizacje', items: (r) => r.entities.organizations },
  { title: 'Osoby', items: (r) => r.entities.people },
  { title: 'Słowa kluczowe', items: (r) => r.keywords, inline: true },
];

export const TABLE_SECTIONS: { title: string; columns: string[]; rows: Read<string[][]> }[] = [
  {
    title: 'Kwoty',
    columns: ['Kwota', 'Waluta', 'Kontekst'],
    rows: (r) => r.amounts.map((a) => [formatAmount(a.value, a.currency), a.currency, a.context]),
  },
  {
    title: 'Daty',
    columns: ['Data', 'Kontekst'],
    rows: (r) => r.dates.map((d) => [formatDate(d.date), d.context]),
  },
];
