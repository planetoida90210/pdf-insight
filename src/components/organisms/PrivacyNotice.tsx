import { providerLabel } from '../../lib/format';
import type { AiProvider } from '../../lib/schema';

type PrivacyNoticeProps = {
  provider: AiProvider | null;
};

export function PrivacyNotice({ provider }: PrivacyNoticeProps) {
  return (
    <p className="muted">
      Treść pliku trafia przez nasz serwer do {providerLabel(provider)}, więc nie wgrywaj poufnych
      dokumentów.
    </p>
  );
}
