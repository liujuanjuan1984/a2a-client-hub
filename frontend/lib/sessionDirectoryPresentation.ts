import { type SessionListItem } from "@/lib/api/sessions";

export type SessionAgentLookup = {
  name: string;
  source: "personal" | "shared";
};

export type SessionAgentPresentation = {
  name: string;
  tone: "personal" | "shared" | "unknown";
};

export const resolveSessionAgentPresentation = (
  item: SessionListItem,
  lookupById: Map<string, SessionAgentLookup>,
): SessionAgentPresentation => {
  const agentId = item.agent_id?.trim();
  if (!agentId) {
    return { name: "Unknown Agent", tone: "unknown" };
  }

  const matched = lookupById.get(agentId);
  if (matched) {
    return { name: matched.name, tone: matched.source };
  }

  if (item.agent_source === "personal" || item.agent_source === "shared") {
    return { name: agentId, tone: item.agent_source };
  }

  return { name: agentId, tone: "unknown" };
};
