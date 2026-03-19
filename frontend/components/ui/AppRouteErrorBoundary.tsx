import type { ErrorBoundaryProps } from "expo-router";
import { Text, View } from "react-native";

import { Button } from "@/components/ui/Button";

export function AppRouteErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  const message =
    typeof error.message === "string" && error.message.trim()
      ? error.message.trim()
      : "An unexpected error interrupted this screen.";

  return (
    <View className="flex-1 items-center justify-center bg-background px-6">
      <View className="w-full max-w-[520px] rounded-3xl border border-red-500/20 bg-surface p-6">
        <Text className="text-lg font-bold text-white">
          Something went wrong
        </Text>
        <Text className="mt-3 text-sm leading-6 text-slate-300">
          This screen crashed during rendering. Retry the route to recover.
        </Text>
        <View className="mt-4 rounded-2xl bg-black/20 px-4 py-3">
          <Text className="text-[12px] leading-5 text-slate-400">
            {message}
          </Text>
        </View>
        <Button
          className="mt-6 self-start"
          label="Retry"
          onPress={() => {
            retry().catch(() => undefined);
          }}
        />
      </View>
    </View>
  );
}
