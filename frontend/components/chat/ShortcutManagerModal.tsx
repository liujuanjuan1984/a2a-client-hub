import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";

import { Button } from "@/components/ui/Button";
import { toast } from "@/lib/toast";
import { useShortcutStore } from "@/store/shortcuts";

export function ShortcutManagerModal({
  visible,
  onClose,
  onUseShortcut,
  initialPrompt,
  agentId,
}: {
  visible: boolean;
  onClose: () => void;
  onUseShortcut: (prompt: string) => void;
  initialPrompt: string;
  agentId?: string | null;
}) {
  const { getShortcutsForAgent, addShortcut, updateShortcut, removeShortcut } =
    useShortcutStore();

  const [shortcutManagerMode, setShortcutManagerMode] = useState<
    "list" | "create" | "edit"
  >("list");
  const [editingShortcutId, setEditingShortcutId] = useState<string | null>(
    null,
  );
  const [shortcutTitle, setShortcutTitle] = useState("");
  const [shortcutPrompt, setShortcutPrompt] = useState("");
  const [isAgentSpecific, setIsAgentSpecific] = useState(false);

  const shortcuts = getShortcutsForAgent(agentId ?? null);

  useEffect(() => {
    if (visible && shortcutManagerMode === "list") {
      setEditingShortcutId(null);
      setShortcutTitle("");
      setShortcutPrompt("");
      setIsAgentSpecific(false);
    }
  }, [visible, shortcutManagerMode]);

  const resetShortcutDraft = () => {
    setEditingShortcutId(null);
    setShortcutTitle("");
    setShortcutPrompt("");
    setIsAgentSpecific(false);
  };

  const closeShortcutManager = () => {
    onClose();
    resetShortcutDraft();
    setShortcutManagerMode("list");
  };

  const openCreateShortcut = () => {
    const inferredTitle = initialPrompt.trim().slice(0, 20) || "New Shortcut";
    setShortcutManagerMode("create");
    setEditingShortcutId(null);
    setShortcutTitle(inferredTitle);
    setShortcutPrompt(initialPrompt.trim());
    setIsAgentSpecific(false);
  };

  const openEditShortcut = (
    shortcutId: string,
    title: string,
    prompt: string,
    specificAgentId: string | null,
  ) => {
    setShortcutManagerMode("edit");
    setEditingShortcutId(shortcutId);
    setShortcutTitle(title);
    setShortcutPrompt(prompt);
    setIsAgentSpecific(specificAgentId !== null);
  };

  const exitShortcutManagerForm = () => {
    setShortcutManagerMode("list");
    resetShortcutDraft();
  };

  const handleSubmitShortcut = async () => {
    const normalizedTitle = shortcutTitle.trim();
    const normalizedPrompt = shortcutPrompt.trim();
    if (!normalizedTitle || !normalizedPrompt) {
      toast.error("Shortcut invalid", "Title and prompt are required.");
      return;
    }

    const targetAgentId = isAgentSpecific ? (agentId ?? null) : null;

    try {
      if (editingShortcutId) {
        await updateShortcut(
          editingShortcutId,
          normalizedTitle,
          normalizedPrompt,
          targetAgentId,
          !isAgentSpecific, // clearAgent
        );
        toast.success(
          "Shortcut updated",
          `"${normalizedTitle}" has been updated.`,
        );
      } else {
        await addShortcut(normalizedTitle, normalizedPrompt, targetAgentId);
        toast.success(
          "Shortcut saved",
          `"${normalizedTitle}" is now available.`,
        );
      }
      exitShortcutManagerForm();
    } catch (error) {
      toast.error(
        editingShortcutId ? "Update shortcut failed" : "Save shortcut failed",
        error instanceof Error ? error.message : "Unknown error",
      );
    }
  };

  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={closeShortcutManager}
    >
      <View className="flex-1 items-center justify-center bg-black/60 px-6">
        <Pressable
          className="absolute inset-0"
          accessibilityRole="button"
          accessibilityLabel="Close shortcut manager"
          onPress={closeShortcutManager}
        />

        <View className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-950 p-4">
          <View className="mb-4 flex-row items-center justify-between">
            <Text className="text-base font-semibold text-white">
              Shortcut Manager
            </Text>
            <Pressable
              onPress={closeShortcutManager}
              className="rounded-lg bg-slate-800 px-2 py-1"
              accessibilityRole="button"
              accessibilityLabel="Close shortcut manager"
            >
              <Ionicons name="close" size={16} color="#cbd5e1" />
            </Pressable>
          </View>

          {shortcutManagerMode === "list" ? (
            <>
              {shortcuts.length === 0 ? (
                <Text className="text-sm text-muted">No shortcuts yet.</Text>
              ) : (
                <ScrollView
                  className="max-h-80"
                  keyboardShouldPersistTaps="handled"
                >
                  {shortcuts.map((cmd) => (
                    <View
                      key={cmd.id}
                      className="mb-2 flex-row items-start rounded-xl border border-slate-800 p-2"
                    >
                      <Pressable
                        className="mr-2 flex-1 px-2 py-1"
                        onPress={() => onUseShortcut(cmd.prompt)}
                      >
                        <Text className="text-sm text-white" numberOfLines={1}>
                          {cmd.title}
                          {cmd.agentId ? " (Agent Specific)" : ""}
                        </Text>
                        <Text
                          className="mt-1 text-xs text-slate-400"
                          numberOfLines={2}
                        >
                          {cmd.prompt}
                        </Text>
                      </Pressable>
                      {!cmd.isDefault ? (
                        <Pressable
                          className="rounded-lg px-2 py-1"
                          accessibilityRole="button"
                          accessibilityLabel={`Edit shortcut ${cmd.title}`}
                          onPress={() =>
                            openEditShortcut(
                              cmd.id,
                              cmd.title,
                              cmd.prompt,
                              cmd.agentId,
                            )
                          }
                        >
                          <Text className="text-xs font-semibold text-sky-300">
                            Edit
                          </Text>
                        </Pressable>
                      ) : null}
                      {!cmd.isDefault && (
                        <Pressable
                          className="rounded-lg px-2 py-1"
                          accessibilityRole="button"
                          accessibilityLabel={`Delete shortcut ${cmd.title}`}
                          onPress={async () => {
                            await removeShortcut(cmd.id).catch(() => {
                              toast.error("Failed to remove shortcut");
                            });
                          }}
                        >
                          <Text className="text-xs font-semibold text-red-400">
                            Del
                          </Text>
                        </Pressable>
                      )}
                    </View>
                  ))}
                </ScrollView>
              )}

              <View className="mt-4 flex-row gap-2">
                <Button
                  label="New Shortcut"
                  onPress={openCreateShortcut}
                  className="flex-1"
                />
                <Button
                  label="Close"
                  variant="secondary"
                  onPress={closeShortcutManager}
                  className="flex-1"
                />
              </View>
            </>
          ) : (
            <>
              <Text className="text-sm text-white">
                {shortcutManagerMode === "edit"
                  ? "Edit shortcut"
                  : "Create shortcut"}
              </Text>
              <TextInput
                className="mt-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                placeholder="Shortcut title"
                placeholderTextColor="#6b7280"
                value={shortcutTitle}
                onChangeText={setShortcutTitle}
              />
              <TextInput
                className="mt-3 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                placeholder="Prompt"
                placeholderTextColor="#6b7280"
                multiline
                value={shortcutPrompt}
                onChangeText={setShortcutPrompt}
                style={{ minHeight: 120 }}
              />
              {agentId ? (
                <View className="mt-3 flex-row items-center justify-between">
                  <Text className="text-sm text-white">
                    Specific to this agent only
                  </Text>
                  <Switch
                    value={isAgentSpecific}
                    onValueChange={setIsAgentSpecific}
                    trackColor={{ false: "#334155", true: "#38bdf8" }}
                    thumbColor="#ffffff"
                  />
                </View>
              ) : null}
              <View className="mt-4 flex-row gap-2">
                <Button
                  label="Cancel"
                  variant="secondary"
                  onPress={exitShortcutManagerForm}
                  className="flex-1"
                />
                <Button
                  label={shortcutManagerMode === "edit" ? "Update" : "Save"}
                  onPress={handleSubmitShortcut}
                  className="flex-1"
                />
              </View>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}
