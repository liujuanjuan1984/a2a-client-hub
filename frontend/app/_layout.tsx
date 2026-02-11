import "../global.css";
import "@expo/metro-runtime";
import { Stack } from "expo-router";
import Head from "expo-router/head";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { Platform } from "react-native";

import { AppProviders } from "@/components/layout/AppProviders";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useSessionStore } from "@/store/session";

export default function RootLayout() {
  const hydrated = useSessionStore((state) => state.hydrated);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    if (typeof document === "undefined" || typeof window === "undefined")
      return;
    const isIOS =
      typeof navigator !== "undefined" &&
      /iPad|iPhone|iPod/.test(navigator.userAgent);
    if (!isIOS) return;

    const root = document.documentElement;
    root.classList.add("ios-web");

    const setAppHeight = () => {
      const height = window.visualViewport?.height ?? window.innerHeight;
      root.style.setProperty("--app-height", `${height}px`);
    };

    setAppHeight();
    window.visualViewport?.addEventListener("resize", setAppHeight);
    window.addEventListener("orientationchange", setAppHeight);
    window.addEventListener("resize", setAppHeight);

    return () => {
      window.visualViewport?.removeEventListener("resize", setAppHeight);
      window.removeEventListener("orientationchange", setAppHeight);
      window.removeEventListener("resize", setAppHeight);
      root.classList.remove("ios-web");
      root.style.removeProperty("--app-height");
    };
  }, []);

  if (!hydrated) {
    return (
      <AppProviders>
        <StatusBar style="light" />
        <FullscreenLoader message="Preparing session..." />
      </AppProviders>
    );
  }

  return (
    <AppProviders>
      {Platform.OS === "web" && (
        <Head>
          <title>A2A Universal Client</title>
        </Head>
      )}
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: "#05070a" },
          headerTintColor: "#fff",
          headerTitleStyle: { color: "#fff" },
          headerShadowVisible: false,
          headerBackButtonDisplayMode: "minimal",
          animation: "fade",
        }}
      >
        <Stack.Screen
          name="(app)"
          options={{
            headerShown: false,
            title: "Home",
            headerBackTitle: "Back",
          }}
        />
        <Stack.Screen
          name="(auth)"
          options={{ animation: "slide_from_right", headerShown: false }}
        />
      </Stack>
    </AppProviders>
  );
}
