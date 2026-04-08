import Ionicons from "@expo/vector-icons/Ionicons";
import React, { useEffect, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export type InvokeMetadataField = {
  name: string;
  required: boolean;
  description?: string | null;
};

export function InvokeMetadataModal({
  visible,
  onClose,
  fields,
  currentBindings,
  onSave,
  onClear,
}: {
  visible: boolean;
  onClose: () => void;
  fields: InvokeMetadataField[];
  currentBindings: Record<string, string>;
  onSave: (bindings: Record<string, string>) => void;
  onClear: () => void;
}) {
  const [draftBindings, setDraftBindings] = useState<Record<string, string>>(
    {},
  );

  useEffect(() => {
    if (!visible) {
      return;
    }
    setDraftBindings(currentBindings);
  }, [currentBindings, visible]);

  const normalizedBindings = useMemo(
    () =>
      Object.entries(draftBindings).reduce<Record<string, string>>(
        (acc, [key, value]) => {
          const normalized = value.trim();
          if (!normalized) {
            return acc;
          }
          acc[key] = normalized;
          return acc;
        },
        {},
      ),
    [draftBindings],
  );

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
          accessibilityLabel="Close invoke metadata modal"
          onPress={onClose}
        />
        <View className="w-full rounded-t-3xl border-t border-white/5 bg-surface p-6 sm:w-[min(92vw,640px)] sm:rounded-3xl sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <View className="flex-1 pr-4">
              <Text className="text-lg font-bold text-white">
                Invoke Metadata
              </Text>
              <Text className="mt-1 text-xs text-slate-400">
                Stored in session metadata as metadata.shared.invoke.bindings.
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close invoke metadata modal"
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>

          <ScrollView className="max-h-[60vh]">
            <View className="gap-4">
              {fields.map((field) => (
                <View key={field.name}>
                  <Input
                    label={field.required ? `${field.name} *` : field.name}
                    value={draftBindings[field.name] ?? ""}
                    onChangeText={(value) =>
                      setDraftBindings((current) => ({
                        ...current,
                        [field.name]: value,
                      }))
                    }
                    autoCapitalize="none"
                    autoCorrect={false}
                    placeholder={field.name}
                    accessibilityLabel={`${field.name} input`}
                  />
                  {field.description ? (
                    <Text className="mt-1 text-xs text-slate-400">
                      {field.description}
                    </Text>
                  ) : null}
                </View>
              ))}
            </View>
          </ScrollView>

          <View className="mt-6 flex-row justify-end gap-3">
            <Button
              label="Clear"
              variant="secondary"
              onPress={() => {
                onClear();
                onClose();
              }}
              disabled={Object.keys(currentBindings).length === 0}
            />
            <Button
              label="Save"
              onPress={() => {
                onSave(normalizedBindings);
                onClose();
              }}
              disabled={fields.some(
                (field) => field.required && !normalizedBindings[field.name],
              )}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}
