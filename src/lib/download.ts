import type { AnalysisResult } from './schema';

export function insightFileName(pdfName: string): string {
  return `${pdfName.replace(/\.pdf$/i, '')}.insight.json`;
}

export function downloadResult(result: AnalysisResult): void {
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = insightFileName(result.document.fileName);
  link.click();
  // Zwolnienie adresu dopiero po zakończeniu bieżącego zdarzenia, inaczej część przeglądarek przerywa pobieranie.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
