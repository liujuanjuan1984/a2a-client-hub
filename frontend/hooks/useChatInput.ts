import { useCallback, useRef, useState } from "react";
import {
  NativeSyntheticEvent,
  Platform,
  TextInput,
  TextInputKeyPressEventData,
} from "react-native";

type WebTextInputKeyPressEvent =
  NativeSyntheticEvent<TextInputKeyPressEventData> & {
    nativeEvent: TextInputKeyPressEventData & {
      shiftKey?: boolean;
      isComposing?: boolean;
    };
    preventDefault?: () => void;
  };

const minInputHeight = 44;
const maxInputHeight = 128;

export function useChatInput(onSend: () => void) {
  const [input, setInput] = useState("");
  const [inputHeight, setInputHeight] = useState(minInputHeight);
  const inputRef = useRef<TextInput>(null);

  const handleInputChange = useCallback((value: string) => {
    setInput(value);
    if (!value) {
      setInputHeight(minInputHeight);
    }
  }, []);

  const handleContentSizeChange = useCallback((height: number) => {
    const nextHeight = Math.min(
      maxInputHeight,
      Math.max(minInputHeight, Math.ceil(height)),
    );
    setInputHeight((prev) => (prev === nextHeight ? prev : nextHeight));
  }, []);

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
        onSend();
      }
    },
    [onSend],
  );

  const clearInput = useCallback(() => {
    setInput("");
    setInputHeight(minInputHeight);
  }, []);

  return {
    inputRef,
    input,
    inputHeight,
    minInputHeight,
    maxInputHeight,
    handleInputChange,
    handleContentSizeChange,
    handleKeyPress,
    setInput,
    setInputHeight,
    clearInput,
  };
}
