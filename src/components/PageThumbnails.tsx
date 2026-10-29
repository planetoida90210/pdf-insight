import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { openPdf, renderPage } from '../lib/pdf';
import { badgesForPage, PAGE_BADGE_LABELS, type PageBadge } from '../lib/pageBadges';
import type { AnalysisResult } from '../lib/schema';

type PageThumbnailsProps = {
  file: File | null;
  result: AnalysisResult;
};

const THUMB_WIDTH = 140;

function Thumbnail({
  pdf,
  pageNumber,
  badges,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  badges: PageBadge[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLLIElement>(null);
  const [visible, setVisible] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '120px' },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !canvasRef.current) return;
    let cancelled = false;
    let task: ReturnType<typeof renderPage> | null = null;

    void (async () => {
      const page = await pdf.getPage(pageNumber);
      if (cancelled || !canvasRef.current) return;
      task = renderPage(page, canvasRef.current, THUMB_WIDTH);
      await task.promise;
      if (!cancelled) setReady(true);
    })();

    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [visible, pdf, pageNumber]);

  return (
    <li
      ref={hostRef}
      id={`page-${pageNumber}`}
      className="thumb"
      tabIndex={-1}
      aria-label={`Strona ${pageNumber}${badges.length ? `, ${badges.map((b) => PAGE_BADGE_LABELS[b]).join(', ')}` : ''}`}
    >
      {!ready ? <div className="thumb__placeholder">…</div> : null}
      <canvas ref={canvasRef} className="thumb__canvas" hidden={!ready} />
      <div className="thumb__label">
        <span>s. {pageNumber}</span>
        {badges.map((badge) => (
          <span
            key={badge}
            className={badge === 'hidden' ? 'thumb__badge thumb__badge--warn' : 'thumb__badge'}
          >
            {PAGE_BADGE_LABELS[badge]}
          </span>
        ))}
      </div>
    </li>
  );
}

function PageThumbnailsFromFile({ file, result }: { file: File; result: AnalysisResult }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [openError, setOpenError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let doc: PDFDocumentProxy | null = null;

    void (async () => {
      try {
        doc = await openPdf(file);
        if (cancelled) {
          await doc.loadingTask.destroy();
          return;
        }
        setPdf(doc);
      } catch {
        if (!cancelled) setOpenError(true);
      }
    })();

    return () => {
      cancelled = true;
      if (doc) void doc.loadingTask.destroy();
    };
  }, [file]);

  if (openError) {
    return <p className="thumbnails-note">Nie udało się wyrenderować miniatur stron tego pliku.</p>;
  }

  if (!pdf) {
    return <p className="thumbnails-note">Ładowanie miniatur…</p>;
  }

  const pages = Array.from({ length: pdf.numPages }, (_, i) => i + 1);

  return (
    <ul className="thumbnails">
      {pages.map((pageNumber) => (
        <Thumbnail
          key={pageNumber}
          pdf={pdf}
          pageNumber={pageNumber}
          badges={badgesForPage(result, pageNumber)}
        />
      ))}
    </ul>
  );
}

export function PageThumbnails({ file, result }: PageThumbnailsProps) {
  if (!file) {
    return (
      <p className="thumbnails-note">
        Miniatury stron są niedostępne dla wyników z historii — plik PDF nie jest przechowywany
        lokalnie.
      </p>
    );
  }

  return <PageThumbnailsFromFile file={file} result={result} />;
}

export function focusPage(page: number): void {
  const el = document.getElementById(`page-${page}`);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  if (el instanceof HTMLElement) el.focus({ preventScroll: true });
}
