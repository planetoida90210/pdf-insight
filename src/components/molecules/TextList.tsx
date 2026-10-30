import { Badge } from '../atoms/Badge';

type TextListProps = {
  items: string[];
  inline?: boolean;
};

// Index keys: the list never changes and its texts may repeat.
export function TextList({ items, inline = false }: TextListProps) {
  return (
    <ul className={inline ? 'list list--inline' : 'list'}>
      {items.map((item, index) => (
        <li key={index} dir="auto">
          {inline ? <Badge>{item}</Badge> : item}
        </li>
      ))}
    </ul>
  );
}
