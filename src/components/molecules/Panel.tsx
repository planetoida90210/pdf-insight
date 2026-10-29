import type { ReactNode, Ref } from 'react';

type PanelProps = {
  title: string;
  children: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
};

// tabIndex={-1}: po zmianie widoku App przenosi fokus na ten nagłówek.
export function Panel({ title, children, headingRef }: PanelProps) {
  return (
    <section className="panel">
      <h2 ref={headingRef} className="panel__title" tabIndex={-1}>
        {title}
      </h2>
      {children}
    </section>
  );
}
