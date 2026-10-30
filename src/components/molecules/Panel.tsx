import type { ReactNode, Ref } from 'react';

type PanelProps = {
  title: string;
  children: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
};

// tabIndex={-1}: App moves focus to this heading when the view changes.
export function Panel({ title, children, headingRef }: PanelProps) {
  return (
    <section className="panel">
      <h2 ref={headingRef} className="panel__title" tabIndex={-1} dir="auto">
        {title}
      </h2>
      {children}
    </section>
  );
}
