import { QueryClientProvider } from "@tanstack/react-query";
import { type PropsWithChildren } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import Toast from "react-native-toast-message";

import { AuthBootstrap } from "@/components/auth/AuthBootstrap";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { queryClient } from "@/services/queryClient";

export function AppProviders({ children }: PropsWithChildren) {
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
