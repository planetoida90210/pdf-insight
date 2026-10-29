import { useState } from 'react';
import { toJson } from '../../lib/download';
import type { AnalysisResult } from '../../lib/schema';
import { Button } from '../atoms/Button';

type JsonPreviewProps = {
  result: AnalysisResult;
};

export function JsonPreview({ result }: JsonPreviewProps) {
  const [status, setStatus] = useState('');
  const json = toJson(result);

  const copy = () =>
    navigator.clipboard.writeText(json).then(
      () => setStatus('Skopiowano.'),
      () => setStatus('Nie udało się skopiować.'),
    );

  return (
    <>
      <div className="row">
        <Button onClick={() => void copy()}>Kopiuj</Button>
        <span className="muted" role="status">
          {status}
        </span>
      </div>
      <details>
        <summary>Podgląd</summary>
        <pre className="json" tabIndex={0}>
          {json}
        </pre>
      </details>
    </>
  );
}
