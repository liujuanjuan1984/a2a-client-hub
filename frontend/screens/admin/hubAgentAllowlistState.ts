import { type HubA2AAllowlistEntryResponse } from "@/lib/api/hubA2aAgentsAdmin";

export type HubAgentAllowlistDraftEntry = {
  id: string;
  existingId: string | null;
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
    existingId: entry.id,
    email: (entry.user_email ?? "").trim(),
    userLabel: (entry.user_email ?? entry.user_name ?? entry.user_id).trim(),
    userId: entry.user_id,
  }));

export const buildNewAllowlistDraftEntry = (
  email: string,
  idSeed: string,
): HubAgentAllowlistDraftEntry => {
  const normalized = normalizeEmail(email);
  return {
    id: `new:${idSeed}`,
    existingId: null,
    email: normalized,
    userLabel: normalized,
    userId: "",
  };
};

export const hasAllowlistEmail = (
  entries: HubAgentAllowlistDraftEntry[],
  email: string,
): boolean => {
  const normalized = normalizeEmail(email);
  if (!normalized) return false;
  return entries.some((entry) => normalizeEmail(entry.email) === normalized);
};

export const deriveAllowlistChanges = (
  baseEntries: HubA2AAllowlistEntryResponse[],
  draftEntries: HubAgentAllowlistDraftEntry[],
): { addEmails: string[]; removeEntryIds: string[] } => {
  const baseIds = new Set(baseEntries.map((entry) => entry.id));
  const currentExistingIds = new Set(
    draftEntries
      .map((entry) => entry.existingId)
      .filter((entryId): entryId is string => Boolean(entryId)),
  );

  const removeEntryIds = Array.from(baseIds).filter(
    (entryId) => !currentExistingIds.has(entryId),
  );
  const addEmails = Array.from(
    new Set(
      draftEntries
        .filter((entry) => entry.existingId == null)
        .map((entry) => normalizeEmail(entry.email))
        .filter(Boolean),
    ),
  );

  return { addEmails, removeEntryIds };
};
