import { useEffect, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { badgesForPage } from '../../lib/pages';
import { openPdf } from '../../lib/pdf';
import type { AnalysisResult } from '../../lib/schema';
import { PageThumbnail } from '../molecules/PageThumbnail';

type PageThumbnailsProps = {
  file: File;
  result: AnalysisResult;
};

export function PageThumbnails({ file, result }: PageThumbnailsProps) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const opening = openPdf(file);
    void opening.then(
      (doc) => {
        if (!cancelled) setPdf(doc);
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    // Destroying the document also frees its pdf.js worker, even while it is still opening.
    return () => {
      cancelled = true;
      void opening.then(
        (doc) => doc.loadingTask.destroy(),
        () => undefined,
      );
    };
  }, [file]);

  if (failed) return <p className="muted">Nie udało się wyświetlić stron.</p>;
  if (!pdf) return <p className="muted">Ładowanie…</p>;

  return (
    <ul className="thumbs">
      {Array.from({ length: pdf.numPages }, (_, index) => index + 1).map((page) => (
        <PageThumbnail key={page} pdf={pdf} page={page} badges={badgesForPage(result, page)} />
      ))}
    </ul>
  );
}
