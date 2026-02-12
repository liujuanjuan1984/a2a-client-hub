export type ItemsEnvelope<T> = {
  items: T[];
  [key: string]: unknown;
};

export const parseListResponse = <T>(response: T[] | ItemsEnvelope<T>) => ({
  items: Array.isArray(response) ? response : response.items,
  envelope: Array.isArray(response) ? null : response,
});
