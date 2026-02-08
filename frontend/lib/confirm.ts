import { Alert, Platform } from "react-native";

import { useConfirmStore } from "@/store/confirm";

type ConfirmOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
};

/**
 * A cross-platform utility to show confirmation dialogs.
 * Uses an in-app dialog on Web and Alert.alert on Native.
 */
export const confirmAction = async ({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  isDestructive = false,
}: ConfirmOptions): Promise<boolean> => {
  if (Platform.OS === "web") {
    return useConfirmStore.getState().open({
      title,
      message,
      confirmLabel,
      cancelLabel,
      isDestructive,
    });
  }

  return new Promise((resolve) => {
    Alert.alert(title, message, [
      {
        text: cancelLabel,
        style: "cancel",
        onPress: () => resolve(false),
      },
      {
        text: confirmLabel,
        style: isDestructive ? "destructive" : "default",
        onPress: () => resolve(true),
      },
    ]);
  });
};
