import { Redirect, Stack } from "expo-router";

import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useSessionStore } from "@/store/session";

export default function AuthLayout() {
  const token = useSessionStore((state) => state.token);
  const hydrated = useSessionStore((state) => state.hydrated);

  if (!hydrated) {
    return <FullscreenLoader message="Loading session..." />;
  }

  if (token) {
    return <Redirect href="/" />;
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
      }}
    />
  );
}
