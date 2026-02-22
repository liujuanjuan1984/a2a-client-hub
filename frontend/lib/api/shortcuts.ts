import { apiRequest } from "@/lib/api/client";

export type ShortcutItem = {
  id: string;
  title: string;
  prompt: string;
  is_default: boolean;
  isDefault?: boolean;
  order: number;
};

export type ShortcutListEnvelope = {
  items: ShortcutItem[];
  pagination: {
    page: number;
    size: number;
    total: number;
    pages: number;
  };
  meta: Record<string, unknown>;
};

export type ShortcutCreatePayload = {
  title: string;
  prompt: string;
  order?: number;
};

export type ShortcutUpdatePayload = {
  title?: string;
  prompt?: string;
  order?: number;
};

const normalizeShortcutItem = (item: Record<string, unknown>): ShortcutItem => {
  const id = typeof item.id === "string" ? item.id.trim() : "";
  const title = typeof item.title === "string" ? item.title : "";
  const prompt = typeof item.prompt === "string" ? item.prompt : "";
  const isDefault =
    typeof item.is_default === "boolean"
      ? item.is_default
      : typeof item.isDefault === "boolean"
        ? item.isDefault
        : false;
  const orderRaw = item.order;
  const order =
    typeof orderRaw === "number" && Number.isFinite(orderRaw)
      ? orderRaw
      : Number.parseInt(String(orderRaw), 10);

  return {
    id,
    title,
    prompt,
    isDefault,
    order: Number.isFinite(order) ? order : 0,
  };
};

const isShortcutListEnvelope = (
  value: unknown,
): value is ShortcutListEnvelope => {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    "items" in (value as Record<string, unknown>) &&
    Array.isArray((value as Record<string, unknown>).items)
  );
};

export const listShortcuts = async (): Promise<ShortcutItem[]> => {
  const response = await apiRequest<ShortcutListEnvelope | ShortcutItem[]>(
    "/me/shortcuts",
  );
  const payload = isShortcutListEnvelope(response) ? response.items : response;
  if (!Array.isArray(payload)) {
    return [];
  }
  return payload
    .map((item) =>
      normalizeShortcutItem(item as Record<string, unknown>),
    )
    .filter((item) => Boolean(item.id));
};

export const createShortcut = (payload: ShortcutCreatePayload) =>
  apiRequest<ShortcutItem, ShortcutCreatePayload>("/me/shortcuts", {
    method: "POST",
    body: payload,
  });

export const updateShortcut = (
  shortcutId: string,
  payload: ShortcutUpdatePayload,
) =>
  apiRequest<ShortcutItem, ShortcutUpdatePayload>(
    `/me/shortcuts/${encodeURIComponent(shortcutId)}`,
    {
      method: "PATCH",
      body: payload,
    },
  );

export const deleteShortcut = (shortcutId: string) =>
  apiRequest<void>(`/me/shortcuts/${encodeURIComponent(shortcutId)}`, {
    method: "DELETE",
  });
