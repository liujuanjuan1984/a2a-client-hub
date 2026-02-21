import { type HubA2AAllowlistEntryResponse } from "@/lib/api/hubA2aAgentsAdmin";

export type HubAgentAllowlistDraftEntry = {
  id: string;
  existingUserId: string | null;
  email: string;
  userLabel: string;
  userId: string;
};

const normalizeEmail = (value: string) => value.trim().toLowerCase();

export const buildAllowlistDraftFromEntries = (
  entries: HubA2AAllowlistEntryResponse[],
): HubAgentAllowlistDraftEntry[] =>
  entries.map((entry) => ({
    id: `existing:${entry.id}`,
    existingUserId: entry.user_id,
    email: (entry.user_email ?? "").trim(),
    userLabel: (entry.user_email ?? entry.user_name ?? entry.user_id).trim(),
    userId: entry.user_id,
  }));

export const hasAllowlistEmail = (
  entries: HubAgentAllowlistDraftEntry[],
  email: string,
): boolean => {
  const normalized = normalizeEmail(email);
  if (!normalized) return false;
  return entries.some((entry) => normalizeEmail(entry.email) === normalized);
};
