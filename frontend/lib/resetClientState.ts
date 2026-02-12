import { queryClient } from "@/services/queryClient";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";
import { useSessionStore } from "@/store/session";
import { useShortcutStore } from "@/store/shortcuts";

export const resetClientState = () => {
  useSessionStore.getState().clearSession();
  useAgentStore.getState().resetAgentUiState();
  useChatStore.getState().clearAll();
  useMessageStore.getState().clearAll();
  useShortcutStore.getState().clearAll();
  queryClient.clear();
};
