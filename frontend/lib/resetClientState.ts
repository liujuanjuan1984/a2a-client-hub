import { queryClient } from "@/services/queryClient";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";
import { useSessionStore } from "@/store/session";

export const resetClientState = () => {
  useSessionStore.getState().clearSession();
  useAgentStore.getState().resetAgents();
  useChatStore.getState().clearAll();
  useMessageStore.getState().clearAll();
  queryClient.clear();
};
