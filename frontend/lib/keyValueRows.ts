import { generateId } from "@/lib/id";

export type KeyValueRow = {
  id: string;
  key: string;
  value: string;
};

export const createKeyValueRow = (): KeyValueRow => ({
  id: generateId(),
  key: "",
  value: "",
});

export const ensureKeyValueRows = (rows: KeyValueRow[]): KeyValueRow[] =>
  rows.length ? rows : [createKeyValueRow()];

export const recordToKeyValueRows = (
  record: Record<string, string>,
): KeyValueRow[] =>
  ensureKeyValueRows(
    Object.entries(record).map(([key, value]) => ({
      id: generateId(),
      key,
      value,
    })),
  );

export const keyValueRowsToRecord = (
  rows: KeyValueRow[],
): Record<string, string> => {
  const record: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    const value = row.value.trim();
    if (!key) continue;
    record[key] = value;
  }
  return record;
};

export const trimKeyValueRows = (
  rows: Pick<KeyValueRow, "key" | "value">[],
): { key: string; value: string }[] =>
  rows
    .map((row) => ({
      key: row.key.trim(),
      value: row.value.trim(),
    }))
    .filter((row) => row.key || row.value);

export const updateKeyValueRows = (
  rows: KeyValueRow[],
  id: string,
  field: "key" | "value",
  value: string,
): KeyValueRow[] =>
  rows.map((row) => (row.id === id ? { ...row, [field]: value } : row));

export const removeKeyValueRow = (
  rows: KeyValueRow[],
  id: string,
  options?: { ensureOne?: boolean },
): KeyValueRow[] => {
  const next = rows.filter((row) => row.id !== id);
  return options?.ensureOne ? ensureKeyValueRows(next) : next;
};

export const appendKeyValueRow = (rows: KeyValueRow[]): KeyValueRow[] => [
  ...rows,
  createKeyValueRow(),
];
