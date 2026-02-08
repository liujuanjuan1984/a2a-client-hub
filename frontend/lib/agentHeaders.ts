import { generateId } from "./id";

export type HeaderEntry = {
  key: string;
  value: string;
};

export type HeaderEntryWithId = HeaderEntry & { id: string };

export const buildHeaderObject = (items: HeaderEntry[]) =>
  items.reduce<Record<string, string>>((acc, item) => {
    const key = item.key.trim();
    const value = item.value.trim();
    if (key && value) {
      acc[key] = value;
    }
    return acc;
  }, {});

export const hasAuthorizationHeader = (headers: Record<string, string>) =>
  Object.keys(headers).some((key) => key.toLowerCase() === "authorization");

export const headersToEntries = (
  headers: Record<string, string>,
): HeaderEntryWithId[] =>
  Object.entries(headers).map(([key, value]) => ({
    id: generateId(),
    key,
    value,
  }));
