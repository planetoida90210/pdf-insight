import { Badge } from '../atoms/Badge';

type TextListProps = {
  items: string[];
  inline?: boolean;
};

// Klucz to indeks: lista się nie zmienia, a teksty mogą się powtarzać.
export function TextList({ items, inline = false }: TextListProps) {
  return (
    <ul className={inline ? 'list list--inline' : 'list'}>
      {items.map((item, index) => (
        <li key={index}>{inline ? <Badge>{item}</Badge> : item}</li>
      ))}
    </ul>
  );
}
