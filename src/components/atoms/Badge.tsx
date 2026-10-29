import type { ReactNode } from 'react';

type BadgeProps = {
  children: ReactNode;
  tone?: 'plain' | 'accent' | 'warn';
};

export function Badge({ children, tone = 'plain' }: BadgeProps) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
