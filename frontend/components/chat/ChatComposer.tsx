import { Ionicons } from "@expo/vector-icons";
import React, { memo, useState } from "react";
import {
  NativeSyntheticEvent,
  Platform,
  Pressable,
  Text,
  TextInput,
  TextInputKeyPressEventData,
  View,
} from "react-native";

import { type GenericCapabilityStatus } from "@/hooks/useExtensionCapabilitiesQuery";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import { type SharedModelSelection } from "@/lib/chat-utils";

export const ChatComposer = memo(function ChatComposer({
  modelSelectionStatus,
  currentDirectory,
  hasInvokeMetadata,
  invokeMetadataRequiredCount,
  pendingInterrupt,
  pendingInterruptCount,
  showShortcutManager,
  onOpenDirectoryPicker,
  onOpenInvokeMetadata,
  onOpenShortcutManager,
  selectedModel,
  onOpenModelPicker,
  inputRef,
  inputResetKey,
  inputDefaultValue,
  inputSelection,
  hasInput,
  hasSendableInput,
  maxInputChars,
  onClearInput,
  onInputChange,
  onSelectionChange,
  onContentSizeChange,
  inputHeight,
  maxInputHeight,
  onSubmit,
  onKeyPress,
  showScrollToBottom,
  onScrollToBottom,
}: {
  modelSelectionStatus: GenericCapabilityStatus;
  currentDirectory?: string | null;
  hasInvokeMetadata: boolean;
  invokeMetadataRequiredCount: number;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  pendingInterruptCount: number;
  showShortcutManager: boolean;
  onOpenDirectoryPicker: () => void;
  onOpenInvokeMetadata: () => void;
  onOpenShortcutManager: () => void;
  selectedModel: SharedModelSelection | null;
  onOpenModelPicker: () => void;
  inputRef: React.RefObject<TextInput | null>;
  inputResetKey: number;
  inputDefaultValue: string;
  inputSelection: { start: number; end: number } | null;
  hasInput: boolean;
  hasSendableInput: boolean;
  maxInputChars: number;
  onClearInput: () => void;
  onInputChange: (value: string) => void;
  onSelectionChange: (start: number, end: number) => void;
  onContentSizeChange: (height: number) => void;
  inputHeight: number;
  maxInputHeight: number;
  onSubmit: () => void;
  onKeyPress: (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => void;
  showScrollToBottom?: boolean;
  onScrollToBottom?: () => void;
}) {
  const [isFocused, setIsFocused] = useState(false);

  const modelLabel = selectedModel
    ? `${selectedModel.providerID} / ${selectedModel.modelID}`
    : "Model: Default";
  const hasDirectory = Boolean(currentDirectory?.trim());
  const invokeMetadataHint =
    invokeMetadataRequiredCount > 0
      ? `${invokeMetadataRequiredCount} required invoke metadata field${
          invokeMetadataRequiredCount === 1 ? "" : "s"
        }`
      : "Configure invoke metadata bindings for this session";

  return (
    <View className="relative border-t border-slate-800 px-2 sm:px-6 py-4">
      {pendingInterrupt ? (
        <View className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <Text className="text-xs text-amber-200">
            Agent is waiting for authorization/input. Resolve the action card
            first.
          </Text>
          {pendingInterruptCount > 1 ? (
            <Text className="mt-1 text-xs text-amber-200">
              {pendingInterruptCount} pending requests are queued for this
              session.
            </Text>
          ) : null}
        </View>
      ) : null}

      <View className="mb-2 flex-row items-center justify-between rounded-xl bg-black/25 px-2 py-1">
        <View className="flex-row items-center gap-2">
          {modelSelectionStatus !== "unsupported" && !isFocused && (
            <Pressable
              className="h-9 max-w-[156px] flex-row items-center gap-2 rounded-xl bg-slate-800/40 px-3"
              onPress={onOpenModelPicker}
              accessibilityRole="button"
              accessibilityLabel="Choose model"
              accessibilityHint={
                modelSelectionStatus === "unknown"
                  ? "Open the model picker and verify discovery availability."
                  : "Open the model picker"
              }
            >
              <Ionicons
                name={
                  modelSelectionStatus === "unknown"
                    ? "help-circle-outline"
                    : "hardware-chip-outline"
                }
                size={16}
                color="#FFFFFF"
              />
              <Text
                className="flex-1 text-xs font-medium text-white"
                numberOfLines={1}
              >
                {modelLabel}
              </Text>
            </Pressable>
          )}

          <Pressable
            className={`h-9 w-14 items-center justify-center rounded-xl ${
              hasDirectory ? "bg-primary" : "bg-slate-800/40"
            }`}
            onPress={onOpenDirectoryPicker}
            accessibilityRole="button"
            accessibilityLabel="Configure working directory"
            accessibilityHint={
              hasDirectory
                ? `Current directory: ${currentDirectory}`
                : "Set the working directory for this session"
            }
          >
            <Ionicons
              name={hasDirectory ? "folder-open" : "folder-open-outline"}
              size={18}
              color={hasDirectory ? "#000000" : "#FFFFFF"}
            />
          </Pressable>

          <Pressable
            className={`h-9 w-14 items-center justify-center rounded-xl ${
              hasInvokeMetadata ? "bg-primary" : "bg-slate-800/40"
            }`}
            onPress={onOpenInvokeMetadata}
            accessibilityRole="button"
            accessibilityLabel="Configure invoke metadata"
            accessibilityHint={invokeMetadataHint}
          >
            <Ionicons
              name={hasInvokeMetadata ? "key" : "key-outline"}
              size={18}
              color={hasInvokeMetadata ? "#000000" : "#FFFFFF"}
            />
          </Pressable>

          <Pressable
            className={`h-9 w-14 items-center justify-center rounded-xl ${
              showShortcutManager ? "bg-primary" : "bg-slate-800/40"
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

          {hasInput && (
            <Pressable
              className="h-9 w-14 items-center justify-center rounded-xl bg-slate-800/40"
              onPress={onClearInput}
              accessibilityRole="button"
              accessibilityLabel="Clear input"
            >
              <Ionicons name="trash-outline" size={18} color="#FFFFFF" />
            </Pressable>
          )}

          {showScrollToBottom && (
            <Pressable
              className="h-9 w-14 items-center justify-center rounded-xl bg-slate-800/40"
              onPress={onScrollToBottom}
              accessibilityRole="button"
              accessibilityLabel="Scroll to bottom"
            >
              <Ionicons name="chevron-down" size={18} color="#FFFFFF" />
            </Pressable>
          )}
        </View>
      </View>

      <View className="flex-row items-end gap-2 rounded-2xl bg-surface p-2">
        <TextInput
          key={inputResetKey}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          ref={inputRef}
          className="flex-1 px-3 py-2 text-white"
          placeholder="Type your message"
          placeholderTextColor="#666666"
          multiline
          defaultValue={inputDefaultValue}
          selection={inputSelection ?? undefined}
          maxLength={maxInputChars}
          onChangeText={onInputChange}
          onSelectionChange={(event) =>
            onSelectionChange(
              event.nativeEvent.selection.start,
              event.nativeEvent.selection.end,
            )
          }
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
        <View className="flex-row items-center pb-1">
          {hasSendableInput && (
            <Pressable
              className={`h-9 w-14 items-center justify-center rounded-xl ${
                pendingInterrupt ? "bg-slate-800/30 opacity-40" : "bg-primary"
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
    </View>
  );
});
