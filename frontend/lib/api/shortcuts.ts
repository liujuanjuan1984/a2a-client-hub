import { apiRequest } from "@/lib/api/client";

export type ShortcutItem = {
  id: string;
  title: string;
  prompt: string;
  is_default: boolean;
  order: number;
  agent_id: string | null;
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
  agent_id?: string | null;
};

export type ShortcutUpdatePayload = {
  title?: string;
  prompt?: string;
  order?: number;
  agent_id?: string | null;
  clear_agent?: boolean;
};

const normalizeShortcutItem = (item: Record<string, unknown>): ShortcutItem => {
  const id = typeof item.id === "string" ? item.id.trim() : "";
  const title = typeof item.title === "string" ? item.title : "";
  const prompt = typeof item.prompt === "string" ? item.prompt : "";
  const isDefault =
    typeof item.is_default === "boolean" ? item.is_default : false;
  const orderRaw = item.order;
  const order =
    typeof orderRaw === "number" && Number.isFinite(orderRaw)
      ? orderRaw
      : Number.parseInt(String(orderRaw), 10);
  const agentId = typeof item.agent_id === "string" ? item.agent_id : null;

  return {
    id,
    title,
    prompt,
    is_default: isDefault,
    order: Number.isFinite(order) ? order : 0,
    agent_id: agentId,
  };
};

export const listShortcuts = async (
  agentId?: string | null,
): Promise<ShortcutItem[]> => {
  const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  const response = await apiRequest<ShortcutListEnvelope>(
    `/me/shortcuts${query}`,
  );
  const payload = response.items;
  return payload
    .map((item) => normalizeShortcutItem(item as Record<string, unknown>))
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
