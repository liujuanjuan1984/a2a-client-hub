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
}) {
  return (
    <View className="relative border-t border-slate-800 px-6 py-4">
      {pendingInterrupt ? (
        <View className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <Text className="text-xs text-amber-200">
            Agent is waiting for authorization/input. Resolve the action card
            first.
          </Text>
        </View>
      ) : null}

      <View className="flex-row items-end gap-2 border-neo border-white bg-surface p-2">
        <Pressable
          className={`h-9 w-9 items-center justify-center border-2 border-white ${
            showShortcutManager ? "bg-neo-yellow" : "bg-surface"
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
        <TextInput
          ref={inputRef}
          className="flex-1 px-3 py-2 text-white"
          placeholder="Type your message"
          placeholderTextColor="#999999"
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
        {input.length > 0 && (
          <Pressable
            className="h-9 w-6 items-center justify-center"
            onPress={() => {
              onInputChange("");
              inputRef.current?.focus();
            }}
            accessibilityRole="button"
            accessibilityLabel="Clear input"
          >
            <Ionicons name="close-circle" size={18} color="#FFFFFF" />
          </Pressable>
        )}
        <Pressable
          className={`h-9 w-9 items-center justify-center border-2 border-white shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none ${
            !input.trim() || Boolean(pendingInterrupt)
              ? "bg-gray-700 opacity-50"
              : "bg-neo-yellow"
          }`}
          testID="chat-send-button"
          onPress={onSubmit}
          disabled={!input.trim() || Boolean(pendingInterrupt)}
          accessibilityRole="button"
          accessibilityLabel="Send message"
        >
          <Ionicons name="send" size={16} color="#000000" />
        </Pressable>
      </View>
    </View>
  );
}
