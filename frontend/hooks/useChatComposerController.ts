import { useCallback, useEffect, useRef, useState } from "react";
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
  ) => Promise<void>;
  appendMessage?: (
    conversationId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
  ) => Promise<void>;
  setSharedModelSelection: (
    conversationId: string,
    agentId: string,
    selection: SharedModelSelection | null,
  ) => void;
  onAfterSend: () => void;
};

const CHAT_COMPOSER_MAX_CHARS = 50_000;
type InputSelection = { start: number; end: number } | null;

export function useChatComposerController({
  activeAgentId,
  conversationId,
  agentSource,
  pendingInterruptActive,
  ensureSession,
  sendMessage,
  appendMessage,
  setSharedModelSelection,
  onAfterSend,
}: UseChatComposerControllerParams) {
  const inputRef = useRef<TextInput>(null);
  const draftInputRef = useRef("");
  const focusInputAfterResetRef = useRef(false);
  const maxLengthToastShownRef = useRef(false);
  const [inputResetKey, setInputResetKey] = useState(0);
  const [inputDefaultValue, setInputDefaultValue] = useState("");
  const [inputSelection, setInputSelection] = useState<InputSelection>(null);
  const [hasInput, setHasInput] = useState(false);
  const [hasSendableInput, setHasSendableInput] = useState(false);
  const [shortcutManagerInitialPrompt, setShortcutManagerInitialPrompt] =
    useState("");
  const [showShortcutManager, setShowShortcutManager] = useState(false);
  const [showDirectoryPicker, setShowDirectoryPicker] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const minInputHeight = 44;
  const maxInputHeight = 128;
  const [inputHeight, setInputHeight] = useState(minInputHeight);

  useEffect(() => {
    if (!focusInputAfterResetRef.current) {
      return;
    }
    focusInputAfterResetRef.current = false;
    inputRef.current?.focus();
  }, [inputResetKey]);

  const updateInputFlags = useCallback((value: string) => {
    const nextHasInput = value.length > 0;
    const nextHasSendableInput = value.trim().length > 0;
    setHasInput((current) =>
      current === nextHasInput ? current : nextHasInput,
    );
    setHasSendableInput((current) =>
      current === nextHasSendableInput ? current : nextHasSendableInput,
    );
  }, []);

  const replaceInput = useCallback(
    (
      value: string,
      options?: {
        focus?: boolean;
        resetHeight?: boolean;
      },
    ) => {
      draftInputRef.current = value;
      updateInputFlags(value);
      setInputDefaultValue(value);
      setInputSelection(
        options?.focus
          ? {
              start: value.length,
              end: value.length,
            }
          : null,
      );
      setInputResetKey((current) => current + 1);
      if (options?.resetHeight || !value) {
        setInputHeight(minInputHeight);
      }
      if (value.length < CHAT_COMPOSER_MAX_CHARS) {
        maxLengthToastShownRef.current = false;
      }
      if (options?.focus) {
        focusInputAfterResetRef.current = true;
      }
    },
    [minInputHeight, updateInputFlags],
  );

  const submitDraft = useCallback(
    (
      action: (
        conversationId: string,
        agentId: string,
        content: string,
        agentSource: AgentSource,
      ) => Promise<void>,
      errorTitle: string,
    ) => {
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
      const input = draftInputRef.current;
      if (!input.trim()) {
        return;
      }

      replaceInput("", { resetHeight: true });
      onAfterSend();
      const sendPromise = action(
        conversationId,
        activeAgentId,
        input,
        agentSource,
      );
      sendPromise.catch((error: unknown) => {
        const message =
          error instanceof Error ? error.message : "Unknown error.";
        const skipToast =
          Boolean(error) &&
          typeof error === "object" &&
          (error as { skipToast?: boolean }).skipToast === true;
        if (!skipToast) {
          toast.error(errorTitle, message);
        }
        if (draftInputRef.current.length === 0) {
          replaceInput(input, { focus: true });
        }
      });
    },
    [
      activeAgentId,
      agentSource,
      conversationId,
      onAfterSend,
      pendingInterruptActive,
      replaceInput,
    ],
  );

  const handleSend = useCallback(() => {
    submitDraft(sendMessage, "Send failed");
  }, [sendMessage, submitDraft]);

  const handleAppend = useCallback(() => {
    if (!appendMessage) {
      return;
    }
    submitDraft(appendMessage, "Append failed");
  }, [appendMessage, submitDraft]);

  const openShortcutManager = useCallback(() => {
    setShortcutManagerInitialPrompt(draftInputRef.current);
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

  const openDirectoryPicker = useCallback(() => {
    setShowDirectoryPicker(true);
  }, []);

  const closeDirectoryPicker = useCallback(() => {
    setShowDirectoryPicker(false);
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
      replaceInput(prompt, { focus: true, resetHeight: true });
      closeShortcutManager();
    },
    [closeShortcutManager, replaceInput],
  );

  const clearInput = useCallback(() => {
    replaceInput("", { focus: true, resetHeight: true });
  }, [replaceInput]);

  const handleInputChange = useCallback(
    (value: string) => {
      const previousValue = draftInputRef.current;
      draftInputRef.current = value;
      updateInputFlags(value);
      if (!value) {
        setInputHeight(minInputHeight);
      }
      if (
        value.length >= CHAT_COMPOSER_MAX_CHARS &&
        previousValue.length < CHAT_COMPOSER_MAX_CHARS &&
        !maxLengthToastShownRef.current
      ) {
        maxLengthToastShownRef.current = true;
        toast.info(
          "Message too long",
          `Messages are limited to ${CHAT_COMPOSER_MAX_CHARS.toLocaleString()} characters.`,
        );
      } else if (value.length < CHAT_COMPOSER_MAX_CHARS) {
        maxLengthToastShownRef.current = false;
      }
    },
    [minInputHeight, updateInputFlags],
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

  const handleSelectionChange = useCallback((start: number, end: number) => {
    setInputSelection((current) => {
      if (current?.start === start && current?.end === end) {
        return current;
      }
      return { start, end };
    });
  }, []);

  return {
    inputRef,
    inputResetKey,
    inputDefaultValue,
    inputSelection,
    hasInput,
    hasSendableInput,
    maxInputChars: CHAT_COMPOSER_MAX_CHARS,
    shortcutManagerInitialPrompt,
    inputHeight,
    maxInputHeight,
    showShortcutManager,
    showDirectoryPicker,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openDirectoryPicker,
    closeDirectoryPicker,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleUseShortcut,
    clearInput,
    handleInputChange,
    handleSelectionChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
    handleAppend,
  };
}
