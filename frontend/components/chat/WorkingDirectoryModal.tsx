import Ionicons from "@expo/vector-icons/Ionicons";
import React, { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export function WorkingDirectoryModal({
  visible,
  onClose,
  currentDirectory,
  onSave,
  onClear,
}: {
  visible: boolean;
  onClose: () => void;
  currentDirectory?: string | null;
  onSave: (directory: string) => void;
  onClear: () => void;
}) {
  const [draftDirectory, setDraftDirectory] = useState("");

  useEffect(() => {
    if (!visible) {
      return;
    }
    setDraftDirectory(currentDirectory ?? "");
  }, [currentDirectory, visible]);

  const normalizedDraft = draftDirectory.trim();

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
          accessibilityLabel="Close working directory modal"
          onPress={onClose}
        />
        <View className="w-full rounded-t-3xl border-t border-white/5 bg-surface p-6 sm:w-[min(92vw,640px)] sm:rounded-3xl sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <View className="flex-1 pr-4">
              <Text className="text-lg font-bold text-white">
                Working Directory
              </Text>
              <Text className="mt-1 text-xs text-slate-400">
                Saved for this conversation and forwarded by the Hub.
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close working directory modal"
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>

          <View className="mb-4 rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Current
            </Text>
            <Text className="mt-1 text-sm text-white" numberOfLines={2}>
              {currentDirectory?.trim() || "Not set"}
            </Text>
          </View>

          <Input
            label="Directory"
            value={draftDirectory}
            onChangeText={setDraftDirectory}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="/workspace/project"
            accessibilityLabel="Working directory input"
          />

          <View className="mt-6 flex-row justify-end gap-3">
            <Button
              label="Clear"
              variant="secondary"
              onPress={() => {
                onClear();
                onClose();
              }}
              disabled={!currentDirectory?.trim()}
            />
            <Button
              label="Save"
              onPress={() => {
                onSave(normalizedDraft);
                onClose();
              }}
              disabled={!normalizedDraft}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}
