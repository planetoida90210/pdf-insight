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
    throw new Error(`Invalid path in case "${patch.name}"`);
  }
  const target = parent as Record<string | number, unknown>;
  if (patch.delete) Reflect.deleteProperty(target, key);
  else target[key] = patch.value;
  return copy;
}

describe('analysisResultSchema', () => {
  it('has shared fixtures to check', () => {
    expect(Object.keys(validFixtures).length).toBeGreaterThan(0);
    expect(umowa).toBeDefined();
  });

  it.each(Object.entries(validFixtures))('accepts the valid result %s', (_, fixture) => {
    const parsed = analysisResultSchema.safeParse(fixture);
    expect(parsed.error).toBeUndefined();
  });

  it.each(invalidCases as Patch[])('rejects $name', (patch) => {
    expect(analysisResultSchema.safeParse(applyPatch(umowa, patch)).success).toBe(false);
  });
});
