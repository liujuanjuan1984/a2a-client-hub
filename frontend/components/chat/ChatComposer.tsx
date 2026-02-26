import { Ionicons } from "@expo/vector-icons";
import React from "react";
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

export function ChatComposer({
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
  showScrollToBottom,
  onScrollToBottom,
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
  onSubmit: () => void;
  onKeyPress: (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => void;
  showScrollToBottom?: boolean;
  onScrollToBottom?: () => void;
}) {
  return (
    <View className="relative border-t border-slate-800 px-3 sm:px-6 py-4">
      {pendingInterrupt ? (
        <View className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <Text className="text-xs text-amber-200">
            Agent is waiting for authorization/input. Resolve the action card
            first.
          </Text>
        </View>
      ) : null}

      <View className="mb-2 flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <Pressable
            className={`h-9 w-9 items-center justify-center rounded-xl ${
              showShortcutManager ? "bg-primary" : "bg-gray-800"
            }`}
            onPress={onOpenShortcutManager}
            accessibilityRole="button"
            accessibilityLabel="Open shortcut manager"
          >
            <Ionicons
              name={showShortcutManager ? "flash" : "flash-outline"}
              size={18}
              color={showShortcutManager ? "#000000" : "#FFFFFF"}
            />
          </Pressable>

          {showScrollToBottom && (
            <Pressable
              className="h-9 w-9 items-center justify-center rounded-xl bg-gray-800"
              onPress={onScrollToBottom}
              accessibilityRole="button"
              accessibilityLabel="Scroll to bottom"
            >
              <Ionicons name="chevron-down" size={18} color="#FFFFFF" />
            </Pressable>
          )}
        </View>

        <View className="flex-row items-center gap-3">
          {input.length > 0 && (
            <Pressable
              className="h-9 px-2 items-center justify-center"
              onPress={() => {
                onInputChange("");
                inputRef.current?.focus();
              }}
              accessibilityRole="button"
              accessibilityLabel="Clear input"
            >
              <Text className="text-xs font-medium text-gray-400">CLEAR</Text>
            </Pressable>
          )}

          {input.trim().length > 0 && (
            <Pressable
              className={`h-9 w-9 items-center justify-center rounded-xl ${
                pendingInterrupt ? "bg-gray-800 opacity-40" : "bg-primary"
              }`}
              testID="chat-send-button"
              onPress={onSubmit}
              disabled={Boolean(pendingInterrupt)}
              accessibilityRole="button"
              accessibilityLabel="Send message"
            >
              <Ionicons name="send" size={16} color="#000000" />
            </Pressable>
          )}
        </View>
      </View>

      <View className="flex-row items-end gap-2 rounded-2xl bg-surface p-2">
        <TextInput
          ref={inputRef}
          className="flex-1 px-3 py-2 text-white"
          placeholder="Type your message"
          placeholderTextColor="#666666"
          multiline
          value={input}
          onChangeText={onInputChange}
          onContentSizeChange={(event) =>
            onContentSizeChange(event.nativeEvent.contentSize.height)
          }
          scrollEnabled={inputHeight >= maxInputHeight}
          textAlignVertical="top"
          style={{ height: inputHeight, fontSize: 16 }}
          submitBehavior={Platform.OS === "web" ? "submit" : undefined}
          onSubmitEditing={Platform.OS === "web" ? undefined : onSubmit}
          onKeyPress={onKeyPress}
          blurOnSubmit={false}
          returnKeyType="default"
        />
      </View>
    </View>
  );
}
