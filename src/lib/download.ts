import type { AnalysisResult } from './schema';

// Preview, copy and download share this text, so the file equals the preview.
export function toJson(result: AnalysisResult): string {
  return JSON.stringify(result, null, 2);
}

// The name comes from the user, so characters not allowed in file names become `_`.
export function insightFileName(pdfName: string): string {
  const base = pdfName.replace(/\.pdf$/i, '').replace(/[\\/:*?"<>|\p{Cc}]/gu, '_');
  return `${base}.insight.json`;
}

export function downloadResult(result: AnalysisResult): void {
  const url = URL.createObjectURL(new Blob([toJson(result)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = insightFileName(result.document.fileName);
  link.click();
  // Revoke after the current event; some browsers cancel the download otherwise.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
