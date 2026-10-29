type PrivacyNoticeProps = {
  providerLabel: string;
};

export function PrivacyNotice({ providerLabel }: PrivacyNoticeProps) {
  return (
    <aside className="privacy" aria-label="Informacja o prywatności">
      <p>
        Plik PDF trafia na nasz serwer w celu odczytu tekstu. Wyodrębniony tekst jest następnie
        wysyłany do <strong>{providerLabel}</strong>. Nie wgrywaj dokumentów poufnych ani objętych
        tajemnicą.
      </p>
    </aside>
  );
}
