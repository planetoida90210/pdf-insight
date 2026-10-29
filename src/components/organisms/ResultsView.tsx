import { documentTitle } from '../../lib/format';
import { downloadResult } from '../../lib/download';
import { focusPage } from '../../lib/pages';
import { DOCUMENT_FIELDS, LIST_SECTIONS, TABLE_SECTIONS } from '../../lib/resultSections';
import type { AnalysisResult } from '../../lib/schema';
import { Button } from '../atoms/Button';
import { DataTable } from '../molecules/DataTable';
import { KeyValueList } from '../molecules/KeyValueList';
import { Panel } from '../molecules/Panel';
import { Section } from '../molecules/Section';
import { TextList } from '../molecules/TextList';
import { JsonPreview } from './JsonPreview';
import { PageThumbnails } from './PageThumbnails';

type ResultsViewProps = {
  result: AnalysisResult;
  // History keeps the result without the file, so an opened entry has no page previews.
  file: File | null;
  onReset: () => void;
};

export function ResultsView({ result, file, onReset }: ResultsViewProps) {
  return (
    <Panel title={documentTitle(result)}>
      <div className="row">
        <Button variant="primary" onClick={() => downloadResult(result)}>
          Pobierz JSON
        </Button>
        <Button onClick={onReset}>Nowa analiza</Button>
      </div>
      <KeyValueList
        items={DOCUMENT_FIELDS.map(({ label, value }) => ({ label, value: value(result) }))}
      />
      <Section title="Podsumowanie">
        <p>{result.summary}</p>
      </Section>
      {LIST_SECTIONS.map(({ title, items, inline }) => (
        <Section key={title} title={title} empty={items(result).length === 0}>
          <TextList items={items(result)} inline={inline} />
        </Section>
      ))}
      {TABLE_SECTIONS.map(({ title, columns, rows }) => (
        <Section key={title} title={title} empty={rows(result).length === 0}>
          <DataTable columns={columns} rows={rows(result)} />
        </Section>
      ))}
      <Section title="Ostrzeżenia" empty={result.warnings.length === 0}>
        <ul className="list">
          {result.warnings.map(({ message, page }, index) => (
            <li key={index}>
              {message}{' '}
              {file && page !== null ? (
                <Button onClick={() => focusPage(page)}>Strona {page}</Button>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
      {file ? (
        <Section title="Strony">
          <PageThumbnails file={file} result={result} />
        </Section>
      ) : null}
      <Section title="JSON">
        <JsonPreview result={result} />
      </Section>
    </Panel>
  );
}
