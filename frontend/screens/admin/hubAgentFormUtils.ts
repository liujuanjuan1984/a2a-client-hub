import { generateId } from "@/lib/id";

export type HeaderRow = {
  id: string;
  key: string;
  value: string;
};

export const recordToHeaderRows = (
  record: Record<string, string>,
): HeaderRow[] => {
  const rows = Object.entries(record).map(([key, value]) => ({
    id: generateId(),
    key,
    value,
  }));
  return rows.length ? rows : [{ id: generateId(), key: "", value: "" }];
};

export const headerRowsToRecord = (
  rows: HeaderRow[],
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

export const validateHttpUrl = (value: string) => {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
};
