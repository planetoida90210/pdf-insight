import type { AiProvider } from '../../lib/schema';
import { Panel } from '../molecules/Panel';
import { StepList } from '../molecules/StepList';
import { UploadZone } from '../molecules/UploadZone';
import { PrivacyNotice } from './PrivacyNotice';

type UploadPanelProps = {
  provider: AiProvider | null;
  onFile: (file: File) => void;
};

export function UploadPanel({ provider, onFile }: UploadPanelProps) {
  return (
    <Panel title="Upuść PDF lub wybierz plik">
      <UploadZone onFile={onFile} />
      <StepList />
      <PrivacyNotice provider={provider} />
    </Panel>
  );
}
