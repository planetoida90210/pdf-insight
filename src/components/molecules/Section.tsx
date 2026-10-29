import type { ReactNode } from 'react';
import { EMPTY_TEXT } from '../../lib/format';

type SectionProps = {
  title: string;
  empty?: boolean;
  children: ReactNode;
};

export function Section({ title, empty = false, children }: SectionProps) {
  return (
    <section className="section">
      <h3 className="section__title">{title}</h3>
      {empty ? <p className="muted">{EMPTY_TEXT}</p> : children}
    </section>
  );
}
