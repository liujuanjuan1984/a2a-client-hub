import { useCallback, useRef, useState } from "react";
import {
  NativeSyntheticEvent,
  Platform,
  TextInput,
  TextInputKeyPressEventData,
} from "react-native";

import type { SharedModelSelection } from "@/lib/chat-utils";
import { toast } from "@/lib/toast";
import type { AgentSource } from "@/store/agents";

type WebTextInputKeyPressEvent =
  NativeSyntheticEvent<TextInputKeyPressEventData> & {
    nativeEvent: TextInputKeyPressEventData & {
      shiftKey?: boolean;
      isComposing?: boolean;
    };
    preventDefault?: () => void;
  };

type UseChatComposerControllerParams = {
  activeAgentId?: string | null;
  conversationId?: string;
  agentSource?: AgentSource | null;
  pendingInterruptActive: boolean;
  ensureSession: (conversationId: string, agentId: string) => void;
  sendMessage: (
    conversationId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
  ) => void;
  setSharedModelSelection: (
    conversationId: string,
    agentId: string,
    selection: SharedModelSelection | null,
  ) => void;
  onAfterSend: () => void;
};

export function useChatComposerController({
  activeAgentId,
  conversationId,
  agentSource,
  pendingInterruptActive,
  ensureSession,
  sendMessage,
  setSharedModelSelection,
  onAfterSend,
}: UseChatComposerControllerParams) {
  const inputRef = useRef<TextInput>(null);
  const [input, setInput] = useState("");
  const [showShortcutManager, setShowShortcutManager] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const minInputHeight = 44;
  const maxInputHeight = 128;
  const [inputHeight, setInputHeight] = useState(minInputHeight);

  const handleSend = useCallback(() => {
    if (!activeAgentId || !conversationId || !agentSource) {
      return;
    }
    if (pendingInterruptActive) {
      toast.info(
        "Action required",
        "Please resolve the interactive action card before sending a new message.",
      );
      return;
    }
    if (!input.trim()) {
      return;
    }

    sendMessage(conversationId, activeAgentId, input, agentSource);
    setInput("");
    setInputHeight(minInputHeight);
    onAfterSend();
  }, [
    activeAgentId,
    agentSource,
    conversationId,
    input,
    minInputHeight,
    onAfterSend,
    pendingInterruptActive,
    sendMessage,
  ]);

  const openShortcutManager = useCallback(() => {
    setShowShortcutManager(true);
  }, []);

  const closeShortcutManager = useCallback(() => {
    setShowShortcutManager(false);
  }, []);

  const openModelPicker = useCallback(() => {
    setShowModelPicker(true);
  }, []);

  const closeModelPicker = useCallback(() => {
    setShowModelPicker(false);
  }, []);

  const handleModelSelect = useCallback(
    (selection: SharedModelSelection) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      ensureSession(conversationId, activeAgentId);
      setSharedModelSelection(conversationId, activeAgentId, selection);
      toast.success(
        "Model updated",
        `${selection.providerID} / ${selection.modelID}`,
      );
    },
    [activeAgentId, conversationId, ensureSession, setSharedModelSelection],
  );

  const clearModelSelection = useCallback(() => {
    if (!conversationId || !activeAgentId) {
      return;
    }
    ensureSession(conversationId, activeAgentId);
    setSharedModelSelection(conversationId, activeAgentId, null);
    toast.success("Model updated", "Using server default model.");
  }, [activeAgentId, conversationId, ensureSession, setSharedModelSelection]);

  const handleUseShortcut = useCallback(
    (prompt: string) => {
      setInput(prompt);
      closeShortcutManager();
      inputRef.current?.focus();
    },
    [closeShortcutManager],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setInput(value);
      if (!value) {
        setInputHeight(minInputHeight);
      }
    },
    [minInputHeight],
  );

  const handleContentSizeChange = useCallback(
    (height: number) => {
      const nextHeight = Math.min(
        maxInputHeight,
        Math.max(minInputHeight, Math.ceil(height)),
      );
      setInputHeight((prev) => (prev === nextHeight ? prev : nextHeight));
    },
    [maxInputHeight, minInputHeight],
  );

  const handleKeyPress = useCallback(
    (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
      const webEvent = e as WebTextInputKeyPressEvent;
      if (
        Platform.OS === "web" &&
        webEvent.nativeEvent.key === "Enter" &&
        !webEvent.nativeEvent.shiftKey &&
        !webEvent.nativeEvent.isComposing
      ) {
        webEvent.preventDefault?.();
        handleSend();
      }
    },
    [handleSend],
  );

  return {
    inputRef,
    input,
    inputHeight,
    maxInputHeight,
    showShortcutManager,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleUseShortcut,
    handleInputChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
  };
}
