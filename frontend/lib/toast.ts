import Toast, { ToastShowParams } from "react-native-toast-message";

/**
 * Unified toast utility for showing non-intrusive notifications.
 */
const show = (
  type: "success" | "error" | "info",
  title: string,
  message?: string,
  options?: Partial<ToastShowParams>,
) => {
  Toast.show({
    type,
    text1: title,
    text2: message,
    position: "top",
    ...options,
  });
};

export const toast = {
  success: (title: string, message?: string) => show("success", title, message),
  error: (title: string, message?: string) => show("error", title, message),
  info: (title: string, message?: string) => show("info", title, message),
};
