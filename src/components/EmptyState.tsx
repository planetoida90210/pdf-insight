import { PrivacyNotice } from './PrivacyNotice';
import { StepOverview } from './StepOverview';
import { UploadZone } from './UploadZone';

type EmptyStateProps = {
  providerLabel: string;
  onFile: (file: File) => void;
};

export function EmptyState({ providerLabel, onFile }: EmptyStateProps) {
  return (
    <section className="panel" aria-labelledby="empty-heading">
      <span className="panel__numeral" aria-hidden="true">
        01
      </span>
      <div className="empty-layout">
        <div className="empty-layout__copy">
          <p className="eyebrow">Start</p>
          <h2 id="empty-heading" className="section-title">
            Zrozum PDF w czterech krokach
          </h2>
          <p className="lede">
            Wgraj dokument. Lokalnie sprawdzimy, czy to poprawny PDF. Serwer odczyta tekst, a model
            AI przygotuje ustrukturyzowany wynik.
          </p>
        </div>
        <div className="empty-layout__work">
          <UploadZone onFile={onFile} />
          <StepOverview compact />
        </div>
        <PrivacyNotice providerLabel={providerLabel} />
      </div>
    </section>
  );
}
