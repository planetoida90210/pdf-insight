import { downloadResult } from '../lib/download';
import {
  DOCUMENT_TYPE_LABELS,
  formatAmount,
  formatDate,
  formatDateTime,
  languageName,
} from '../lib/format';
import type { AnalysisResult } from '../lib/schema';
import { focusPage, PageThumbnails } from './PageThumbnails';
import { JsonPreview } from './JsonPreview';

type ResultsViewProps = {
  result: AnalysisResult;
  file: File | null;
  onReset: () => void;
};

export function ResultsView({ result, file, onReset }: ResultsViewProps) {
  const { document: doc } = result;
  const title = doc.title ?? doc.fileName;

  return (
    <section className="panel results" aria-labelledby="result-heading">
      <span className="panel__numeral" aria-hidden="true">
        04
      </span>
      <p className="eyebrow">Wynik</p>
      <h2 id="result-heading" className="section-title">
        Analiza gotowa
      </h2>

      <div className="results__actions">
        <button type="button" className="btn btn--primary" onClick={() => downloadResult(result)}>
          Pobierz JSON
        </button>
        <button type="button" className="btn btn--ghost" onClick={onReset}>
          Analizuj kolejny plik
        </button>
      </div>

      <article className="doc-card" aria-label="Karta dokumentu">
        <h3 className="doc-card__title">{title}</h3>
        <dl className="doc-card__meta">
          <div>
            <dt>Typ</dt>
            <dd>{DOCUMENT_TYPE_LABELS[doc.type]}</dd>
          </div>
          <div>
            <dt>Język</dt>
            <dd>{languageName(doc.language)}</dd>
          </div>
          <div>
            <dt>Data dokumentu</dt>
            <dd>{doc.date ? formatDate(doc.date) : '—'}</dd>
          </div>
          <div>
            <dt>Strony</dt>
            <dd>{doc.pages}</dd>
          </div>
          <div>
            <dt>Plik</dt>
            <dd>{doc.fileName}</dd>
          </div>
          <div>
            <dt>Analiza</dt>
            <dd>{formatDateTime(result.meta.analyzedAt)}</dd>
          </div>
        </dl>
      </article>

      <section className="result-block" aria-labelledby="summary-heading">
        <h3 id="summary-heading" className="result-block__title">
          Podsumowanie
        </h3>
        <p>{result.summary}</p>
      </section>

      <section className="result-block" aria-labelledby="keypoints-heading">
        <h3 id="keypoints-heading" className="result-block__title">
          Kluczowe punkty
        </h3>
        {result.keyPoints.length === 0 ? (
          <p className="result-block__empty">Brak kluczowych punktów</p>
        ) : (
          <ul className="key-points">
            {result.keyPoints.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="result-block" aria-labelledby="entities-heading">
        <h3 id="entities-heading" className="result-block__title">
          Podmioty
        </h3>
        <div className="entity-lists">
          <div>
            <h4>Organizacje</h4>
            {result.entities.organizations.length === 0 ? (
              <p className="result-block__empty">Brak organizacji w dokumencie</p>
            ) : (
              <ul>
                {result.entities.organizations.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h4>Osoby</h4>
            {result.entities.people.length === 0 ? (
              <p className="result-block__empty">Brak osób w dokumencie</p>
            ) : (
              <ul>
                {result.entities.people.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="result-block" aria-labelledby="amounts-heading">
        <h3 id="amounts-heading" className="result-block__title">
          Kwoty
        </h3>
        {result.amounts.length === 0 ? (
          <p className="result-block__empty">Brak kwot w dokumencie</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Kwota</th>
                  <th scope="col">Waluta</th>
                  <th scope="col">Kontekst</th>
                </tr>
              </thead>
              <tbody>
                {result.amounts.map((row) => (
                  <tr key={`${row.value}-${row.currency}-${row.context}`}>
                    <td className="data-table__amount">{formatAmount(row.value, row.currency)}</td>
                    <td className="data-table__currency">{row.currency}</td>
                    <td>{row.context}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="result-block" aria-labelledby="dates-heading">
        <h3 id="dates-heading" className="result-block__title">
          Daty
        </h3>
        {result.dates.length === 0 ? (
          <p className="result-block__empty">Brak dat w dokumencie</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Data</th>
                  <th scope="col">Kontekst</th>
                </tr>
              </thead>
              <tbody>
                {result.dates.map((row) => (
                  <tr key={`${row.date}-${row.context}`}>
                    <td>{formatDate(row.date)}</td>
                    <td>{row.context}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="result-block" aria-labelledby="keywords-heading">
        <h3 id="keywords-heading" className="result-block__title">
          Słowa kluczowe
        </h3>
        {result.keywords.length === 0 ? (
          <p className="result-block__empty">Brak słów kluczowych</p>
        ) : (
          <ul className="keyword-list">
            {result.keywords.map((word) => (
              <li key={word}>{word}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="result-block" aria-labelledby="warnings-heading">
        <h3 id="warnings-heading" className="result-block__title">
          Ostrzeżenia
        </h3>
        {result.warnings.length === 0 ? (
          <p className="result-block__empty">Brak ostrzeżeń</p>
        ) : (
          <ul className="warnings">
            {result.warnings.map((warning) => (
              <li
                key={`${warning.code}-${warning.page ?? 'x'}-${warning.message}`}
                className="warnings__item"
              >
                <span className="warnings__code">
                  {warning.code}
                  {warning.page != null ? ` · strona ${warning.page}` : ''}
                </span>
                <p className="warnings__message">{warning.message}</p>
                {warning.page != null ? (
                  <button
                    type="button"
                    className="warnings__link"
                    onClick={() => {
                      const page = warning.page;
                      if (page != null) focusPage(page);
                    }}
                  >
                    Przejdź do strony {warning.page}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="result-block" aria-labelledby="pages-heading">
        <h3 id="pages-heading" className="result-block__title">
          Strony dokumentu
        </h3>
        <PageThumbnails file={file} result={result} />
      </section>

      <section className="result-block" aria-labelledby="json-heading">
        <h3 id="json-heading" className="result-block__title">
          Eksport
        </h3>
        <JsonPreview result={result} />
      </section>
    </section>
  );
}
