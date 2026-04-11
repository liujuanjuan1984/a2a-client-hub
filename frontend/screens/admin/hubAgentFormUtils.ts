import {
  type KeyValueRow,
  keyValueRowsToRecord,
  recordToKeyValueRows,
} from "@/lib/keyValueRows";

export type HeaderRow = KeyValueRow;

export const recordToHeaderRows = (
  record: Record<string, string>,
): HeaderRow[] => recordToKeyValueRows(record);

export const headerRowsToRecord = (rows: HeaderRow[]): Record<string, string> =>
  keyValueRowsToRecord(rows);

export const parseTags = (value: string): string[] => {
  const raw = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  // Preserve input order while de-duping.
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const tag of raw) {
    if (seen.has(tag)) continue;
    seen.add(tag);
    tags.push(tag);
  }
  return tags;
};
