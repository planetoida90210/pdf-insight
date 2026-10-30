type KeyValueListProps = {
  items: { label: string; value: string }[];
};

export function KeyValueList({ items }: KeyValueListProps) {
  return (
    <dl className="key-values">
      {items.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd dir="auto">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
