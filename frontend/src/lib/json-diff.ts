export interface JsonChange {
  path: string[];
  /** `undefined` when the field did not exist on that side. */
  before: unknown;
  after: unknown;
}

const isMap = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The fields that differ between two JSON values. A list that changed length counts as one change. */
export function jsonDiff(before: unknown, after: unknown, path: string[] = []): JsonChange[] {
  if (isMap(before) && isMap(after)) {
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((k) => jsonDiff(before[k], after[k], [...path, k]));
  }
  if (Array.isArray(before) && Array.isArray(after) && before.length === after.length) {
    return before.flatMap((v, i) => jsonDiff(v, after[i], [...path, String(i)]));
  }
  return JSON.stringify(before) === JSON.stringify(after) ? [] : [{ path, before, after }];
}
