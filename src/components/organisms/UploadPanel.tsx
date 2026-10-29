import { Panel } from '../molecules/Panel';
import { StepList } from '../molecules/StepList';
import { UploadZone } from '../molecules/UploadZone';

type UploadPanelProps = {
  onFile: (file: File) => void;
};

export function UploadPanel({ onFile }: UploadPanelProps) {
  return (
    <Panel title="Upuść PDF lub wybierz plik">
      <UploadZone onFile={onFile} />
      <StepList />
      <p className="muted">Plik trafia do API AI.</p>
    </Panel>
  );
}
