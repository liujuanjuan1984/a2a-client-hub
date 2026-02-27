import { useEffect } from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { blurActiveElement } from "@/lib/focus";
import { useConfirmStore } from "@/store/confirm";

export function ConfirmDialog() {
  const request = useConfirmStore((state) => state.request);
  const respond = useConfirmStore((state) => state.respond);

  useEffect(() => {
    if (!request) return;
    // Avoid keeping the underlying input focused while a dialog is open (web).
    blurActiveElement();
  }, [request]);

  if (!request) return null;

  return (
    <Modal
      transparent
      visible
      animationType="fade"
      onRequestClose={() => respond(false)}
    >
      <View className="flex-1 items-center justify-center bg-black/60 px-4">
        <Pressable
          className="absolute inset-0"
          accessibilityRole="button"
          accessibilityLabel="Dismiss dialog"
          onPress={() => respond(false)}
        />

        <View className="w-full max-w-md rounded-3xl border border-slate-700 bg-slate-950 p-5">
          <Text className="text-base font-semibold text-white">
            {request.title}
          </Text>
          <Text className="mt-2 text-sm text-slate-300">{request.message}</Text>

          <View className="mt-5 flex-row items-center justify-between gap-3">
            <Button
              label={request.cancelLabel}
              variant="secondary"
              onPress={() => respond(false)}
            />
            <Button
              label={request.confirmLabel}
              variant={request.isDestructive ? "danger" : "primary"}
              onPress={() => respond(true)}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}
