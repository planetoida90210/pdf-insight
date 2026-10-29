import { describe, expect, it } from 'vitest';
import invalidCases from '../../schema/fixtures/invalid-cases.json';
import { analysisResultSchema } from './schema';

const validFixtures = import.meta.glob<unknown>('../../schema/fixtures/valid/*.json', {
  eager: true,
  import: 'default',
});
const umowa = validFixtures['../../schema/fixtures/valid/umowa.json'];

type Patch = { name: string; path: (string | number)[]; value?: unknown; delete?: boolean };

function applyPatch(source: unknown, patch: Patch): unknown {
  const copy: unknown = structuredClone(source);
  const parentPath = patch.path.slice(0, -1);
  const key = patch.path.at(-1);
  let parent = copy;
  for (const segment of parentPath) {
    parent = (parent as Record<string | number, unknown>)[segment];
  }
  if (key === undefined || typeof parent !== 'object' || parent === null) {
    throw new Error(`Niepoprawna ścieżka w przypadku "${patch.name}"`);
  }
  const target = parent as Record<string | number, unknown>;
  if (patch.delete) Reflect.deleteProperty(target, key);
  else target[key] = patch.value;
  return copy;
}

// Pydantic odrzuca puste napisy w tych polach, a wspólne fikstury tego nie sprawdzają.
const emptyTextCases: Patch[] = [
  { name: 'empty title', path: ['document', 'title'], value: ' ' },
  { name: 'empty organization', path: ['entities', 'organizations'], value: [''] },
  { name: 'empty person', path: ['entities', 'people'], value: [''] },
  { name: 'empty keyword', path: ['keywords'], value: [''] },
];

describe('analysisResultSchema', () => {
  it('ma wspólne fikstury do sprawdzenia', () => {
    expect(Object.keys(validFixtures).length).toBeGreaterThan(0);
    expect(umowa).toBeDefined();
  });

  it.each(Object.entries(validFixtures))('akceptuje poprawny wynik %s', (_, fixture) => {
    const parsed = analysisResultSchema.safeParse(fixture);
    expect(parsed.error).toBeUndefined();
  });

  it.each(
    [...(invalidCases as Patch[]), ...emptyTextCases].map((patch) => [patch.name, patch] as const),
  )('odrzuca wynik: %s', (_, patch) => {
    expect(analysisResultSchema.safeParse(applyPatch(umowa, patch)).success).toBe(false);
  });
});
