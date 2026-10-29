import type { ButtonHTMLAttributes } from 'react';

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'type'> & {
  variant?: 'primary' | 'ghost';
};

export function Button({ variant = 'ghost', ...props }: ButtonProps) {
  return <button {...props} type="button" className={`button button--${variant}`} />;
}
