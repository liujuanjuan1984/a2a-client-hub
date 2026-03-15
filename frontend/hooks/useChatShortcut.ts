import { useCallback } from "react";
import { TextInput } from "react-native";

export function useChatShortcut({
  setInput,
  closeShortcutManager,
  inputRef,
}: {
  setInput: (value: string) => void;
  closeShortcutManager: () => void;
  inputRef: React.RefObject<TextInput>;
}) {
  const handleUseShortcut = useCallback(
    (prompt: string) => {
      setInput(prompt);
      closeShortcutManager();
      inputRef.current?.focus();
    },
    [closeShortcutManager, inputRef, setInput],
  );

  return { handleUseShortcut };
}
