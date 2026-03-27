import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

type SessionCommandDraft = {
  command: string;
  arguments: string;
  prompt: string;
};

export function SessionCommandModal({
  visible,
  onClose,
  externalSessionId,
  onSubmit,
  submitting,
}: {
  visible: boolean;
  onClose: () => void;
  externalSessionId: string;
  onSubmit: (draft: SessionCommandDraft) => Promise<boolean>;
  submitting: boolean;
}) {
  const [command, setCommand] = useState("");
  const [argumentsText, setArgumentsText] = useState("");
  const [prompt, setPrompt] = useState("");

  useEffect(() => {
    if (!visible) {
      return;
    }
    setCommand("");
    setArgumentsText("");
    setPrompt("");
  }, [visible]);

  const normalizedCommand = command.trim();
  const normalizedArguments = argumentsText.trim();
  const normalizedPrompt = prompt.trim();

  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
    >
      <View className="flex-1 justify-end bg-black/60 sm:items-center sm:justify-center">
        <Pressable
          className="absolute inset-0"
          accessibilityRole="button"
          accessibilityLabel="Close session command modal"
          onPress={submitting ? undefined : onClose}
        />
        <View className="w-full rounded-t-3xl border-t border-white/5 bg-surface p-6 sm:w-[min(92vw,640px)] sm:rounded-3xl sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <View className="flex-1 pr-4">
              <Text className="text-lg font-bold text-white">
                Session Command
              </Text>
              <Text className="mt-1 text-xs text-slate-400">
                Sends a control command to the active upstream session.
              </Text>
            </View>
            <Pressable
              onPress={submitting ? undefined : onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close session command modal"
              disabled={submitting}
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>

          <View className="mb-4 rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Bound Session
            </Text>
            <Text className="mt-1 text-sm text-white" numberOfLines={2}>
              {externalSessionId}
            </Text>
          </View>

          <View className="gap-4">
            <Input
              label="Command"
              value={command}
              onChangeText={setCommand}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="/review"
              accessibilityLabel="Session command input"
            />
            <Input
              label="Arguments"
              value={argumentsText}
              onChangeText={setArgumentsText}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="--quick"
              accessibilityLabel="Session command arguments input"
            />
            <Input
              label="Prompt"
              value={prompt}
              onChangeText={setPrompt}
              autoCapitalize="sentences"
              autoCorrect={false}
              placeholder="Optional additional instruction"
              accessibilityLabel="Session command prompt input"
              multiline
              textAlignVertical="top"
              className="min-h-[108px] pt-3"
            />
          </View>

          <View className="mt-6 flex-row justify-end gap-3">
            <Button
              label="Cancel"
              variant="secondary"
              onPress={onClose}
              disabled={submitting}
            />
            <Button
              label="Run Command"
              onPress={async () => {
                const ok = await onSubmit({
                  command: normalizedCommand,
                  arguments: normalizedArguments,
                  prompt: normalizedPrompt,
                });
                if (ok) {
                  onClose();
                }
              }}
              loading={submitting}
              disabled={!normalizedCommand || !normalizedArguments}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}
