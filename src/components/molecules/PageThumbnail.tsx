import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { PAGE_BADGES, pageElementId, type PageBadge } from '../../lib/pages';
import { renderPage } from '../../lib/pdf';
import { Badge } from '../atoms/Badge';

const THUMB_WIDTH_PX = 140;
const PRELOAD_MARGIN = '200px';

type PageThumbnailProps = {
  pdf: PDFDocumentProxy;
  page: number;
  badges: PageBadge[];
};

export function PageThumbnail({ pdf, page, badges }: PageThumbnailProps) {
  const itemRef = useRef<HTMLLIElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);
  const labels = badges.map((badge) => PAGE_BADGES[badge].label);

  // Strona rysuje się dopiero, gdy zbliża się do widoku, więc długie dokumenty nie blokują przeglądarki.
  useEffect(() => {
    const item = itemRef.current;
    if (visible || !item) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry?.isIntersecting ?? false),
      { rootMargin: PRELOAD_MARGIN },
    );
    observer.observe(item);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!visible || !canvas) return;
    let cancelled = false;
    let task: RenderTask | undefined;
    pdf
      .getPage(page)
      .then((proxy) => {
        if (cancelled) return;
        task = renderPage(proxy, canvas, THUMB_WIDTH_PX);
        return task.promise;
      })
      // Anulowane rysowanie albo zamknięty dokument: miniatura zostaje pustym polem.
      .catch(() => undefined);
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [visible, pdf, page]);

  return (
    <li
      ref={itemRef}
      id={pageElementId(page)}
      className="thumb"
      tabIndex={-1}
      aria-label={[`Strona ${page}`, ...labels].join(', ')}
    >
      <canvas ref={canvasRef} />
      <p className="row">
        {page}
        {badges.map((badge) => (
          <Badge key={badge} tone={PAGE_BADGES[badge].tone}>
            {PAGE_BADGES[badge].label}
          </Badge>
        ))}
      </p>
    </li>
  );
}
