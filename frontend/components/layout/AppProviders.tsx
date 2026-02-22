import { QueryClientProvider, focusManager } from "@tanstack/react-query";
import { useEffect, type PropsWithChildren } from "react";
import { AppState, type AppStateStatus, Platform } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import Toast from "react-native-toast-message";

import { AuthBootstrap } from "@/components/auth/AuthBootstrap";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { queryClient } from "@/services/queryClient";

function onAppStateChange(status: AppStateStatus) {
  if (Platform.OS !== "web") {
    focusManager.setFocused(status === "active");
  }
}

export function AppProviders({ children }: PropsWithChildren) {
  useEffect(() => {
    if (!AppState || typeof AppState.addEventListener !== "function") {
      return;
    }
    const subscription = AppState.addEventListener("change", onAppStateChange);
    return () => subscription?.remove?.();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <AuthBootstrap />
          {children}
          <Toast />
          <ConfirmDialog />
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
