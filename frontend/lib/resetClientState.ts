import { queryClient } from "@/services/queryClient";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

const removeLegacyPersistKey = (key: string) => {
  import("@/lib/storage/mmkv")
    .then(({ mmkvStateStorage }) => {
      return Promise.resolve(mmkvStateStorage.removeItem(key));
    })
    .catch(() => undefined);
};

export const resetAuthBoundState = () => {
  useSessionStore.getState().clearSession();
  useAgentStore.getState().resetAgentUiState();
  useChatStore.getState().clearAll();
  removeLegacyPersistKey("a2a-client-hub.messages");
  queryClient.clear();
};
