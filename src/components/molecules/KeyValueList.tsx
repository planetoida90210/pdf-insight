type KeyValueListProps = {
  items: { label: string; value: string }[];
};

export function KeyValueList({ items }: KeyValueListProps) {
  return (
    <dl className="key-values">
      {items.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
