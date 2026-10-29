import type { AnalysisResult } from './schema';

// Podgląd, kopiowanie i pobieranie używają tego samego tekstu, więc plik równa się podglądowi.
export function toJson(result: AnalysisResult): string {
  return JSON.stringify(result, null, 2);
}

export function insightFileName(pdfName: string): string {
  return `${pdfName.replace(/\.pdf$/i, '')}.insight.json`;
}

export function downloadResult(result: AnalysisResult): void {
  const url = URL.createObjectURL(new Blob([toJson(result)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = insightFileName(result.document.fileName);
  link.click();
  // Zwolnienie adresu dopiero po zakończeniu bieżącego zdarzenia, inaczej część przeglądarek przerywa pobieranie.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
