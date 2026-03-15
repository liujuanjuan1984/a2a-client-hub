import { useChatInput } from "./useChatInput";

export function useChatMessaging(onSend: (text: string) => void) {
  const input = useChatInput(() => onSend(input.input));

  return {
    ref: input.inputRef,
    value: input.input,
    height: input.inputHeight,
    maxHeight: input.maxInputHeight,
    onChange: input.handleInputChange,
    onContentSizeChange: input.handleContentSizeChange,
    onKeyPress: input.handleKeyPress,
    onSend: () => onSend(input.input),
    clear: input.clearInput,
    setInput: input.setInput,
  };
}
