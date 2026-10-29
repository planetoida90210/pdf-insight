import { useState } from 'react';
import type { AnalysisResult } from '../lib/schema';

type JsonPreviewProps = {
  result: AnalysisResult;
};

export function JsonPreview({ result }: JsonPreviewProps) {
  const [copied, setCopied] = useState(false);
  const pretty = JSON.stringify(result, null, 2);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(pretty);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <details className="json-preview">
      <summary className="json-preview__summary">
        <span>Podgląd JSON</span>
        <span>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={(event) => {
              event.preventDefault();
              void copy();
            }}
          >
            Kopiuj
          </button>
          {copied ? (
            <span className="copy-feedback" role="status">
              {' '}
              Skopiowano
            </span>
          ) : null}
        </span>
      </summary>
      <pre className="json-preview__code">
        <code>{pretty}</code>
      </pre>
    </details>
  );
}
