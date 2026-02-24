import { Ionicons } from "@expo/vector-icons";
import React, { memo, useCallback, useEffect, useState } from "react";
import {
  NativeSyntheticEvent,
  Platform,
  Pressable,
  Text,
  TextInput,
  TextInputKeyPressEventData,
  View,
} from "react-native";

import { type RuntimeInterrupt } from "@/lib/api/chat-utils";

const MAX_INPUT_LENGTH = 100000;

const ShortcutButton = memo(
  ({ active, onPress }: { active: boolean; onPress: () => void }) => (
    <Pressable
      className={`h-9 w-9 items-center justify-center rounded-xl ${
        active ? "bg-primary" : "bg-slate-800"
      }`}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel="Open shortcut manager"
    >
      <Ionicons
        name={active ? "flash" : "flash-outline"}
        size={18}
        color={active ? "#ffffff" : "#94a3b8"}
      />
    </Pressable>
  ),
);

const SendButton = memo(
  ({ disabled, onPress }: { disabled: boolean; onPress: () => void }) => (
    <Pressable
      className={`h-9 w-9 items-center justify-center rounded-xl ${
        disabled ? "bg-slate-800 opacity-50" : "bg-primary"
      }`}
      testID="chat-send-button"
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel="Send message"
    >
      <Ionicons name="send" size={16} color="#ffffff" />
    </Pressable>
  ),
);

const InterruptWarning = memo(
  ({ pendingInterrupt }: { pendingInterrupt: RuntimeInterrupt | null }) => {
    if (!pendingInterrupt) return null;
    return (
      <View className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
        <Text className="text-xs text-amber-200">
          Agent is waiting for authorization/input. Resolve the action card
          first.
        </Text>
      </View>
    );
  },
);

export const ChatComposer = memo(
  ({
    pendingInterrupt,
    showShortcutManager,
    onOpenShortcutManager,
    inputRef,
    input,
    onInputChange,
    onContentSizeChange,
    inputHeight,
    maxInputHeight,
    onSubmit,
    onKeyPress,
  }: {
    pendingInterrupt: RuntimeInterrupt | null;
    showShortcutManager: boolean;
    onOpenShortcutManager: () => void;
    inputRef: React.RefObject<TextInput | null>;
    input: string;
    onInputChange: (value: string) => void;
    onContentSizeChange: (height: number) => void;
    inputHeight: number;
    maxInputHeight: number;
    onSubmit: (value?: string) => void;
    onKeyPress: (
      e: NativeSyntheticEvent<TextInputKeyPressEventData>,
      value?: string,
    ) => void;
  }) => {
    const [localValue, setLocalValue] = useState(input);

    useEffect(() => {
      setLocalValue(input);
    }, [input]);

    const handleInputChangeInternal = useCallback(
      (value: string) => {
        if (value.length > MAX_INPUT_LENGTH) return;
        setLocalValue(value);
        // Only sync to parent if emptiness changes to keep send button up to date
        // or if it's a small change. For large text, we rely on contentSizeChange or submit to sync.
        const wasEmpty = !input.trim();
        const nowEmpty = !value.trim();
        if (wasEmpty !== nowEmpty || value === "") {
          onInputChange(value);
        }
      },
      [input, onInputChange],
    );

    const handleContentSizeChangeInternal = useCallback(
      (height: number) => {
        onInputChange(localValue);
        onContentSizeChange(height);
      },
      [localValue, onContentSizeChange, onInputChange],
    );

    const handleSubmitInternal = useCallback(() => {
      onSubmit(localValue);
    }, [localValue, onSubmit]);

    const handleKeyPressInternal = useCallback(
      (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
        onKeyPress(e, localValue);
      },
      [localValue, onKeyPress],
    );

    return (
      <View className="relative border-t border-slate-800 px-6 py-4">
        <InterruptWarning pendingInterrupt={pendingInterrupt} />

        <View className="flex-row items-end gap-2 rounded-3xl border border-slate-800 bg-slate-900/50 p-2">
          <ShortcutButton
            active={showShortcutManager}
            onPress={onOpenShortcutManager}
          />
          <TextInput
            ref={inputRef}
            className="flex-1 px-3 py-2 text-white"
            placeholder="Type your message"
            placeholderTextColor="#6b7280"
            multiline
            value={localValue}
            onChangeText={handleInputChangeInternal}
            onContentSizeChange={(event) =>
              handleContentSizeChangeInternal(
                event.nativeEvent.contentSize.height,
              )
            }
            scrollEnabled={inputHeight >= maxInputHeight}
            textAlignVertical="top"
            style={{ height: inputHeight, fontSize: 16 }}
            submitBehavior={Platform.OS === "web" ? "submit" : undefined}
            onSubmitEditing={
              Platform.OS === "web" ? undefined : handleSubmitInternal
            }
            onKeyPress={handleKeyPressInternal}
            blurOnSubmit={false}
            returnKeyType="default"
          />
          <SendButton
            disabled={!localValue.trim() || Boolean(pendingInterrupt)}
            onPress={handleSubmitInternal}
          />
        </View>
      </View>
    );
  },
);
