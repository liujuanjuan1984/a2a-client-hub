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
  const webHead =
    Platform.OS === "web" ? (
      <Head>
        <title>A2AClientHub</title>
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta
          name="apple-mobile-web-app-status-bar-style"
          content="black-translucent"
        />
      </Head>
    ) : null;

  useEffect(() => {
    if (Platform.OS !== "web") return;
    if (typeof document === "undefined" || typeof window === "undefined")
      return;
    const isMobile =
      typeof navigator !== "undefined" &&
      /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
        navigator.userAgent,
      );

    if (!isMobile) return;

    const root = document.documentElement;
    root.classList.add("app-web");

    const setAppHeight = () => {
      if (window.visualViewport) {
        const height = window.visualViewport.height;
        root.style.setProperty("--app-height", `${height}px`);
      } else {
        root.style.setProperty("--app-height", `${window.innerHeight}px`);
      }
    };

    setAppHeight();
    window.visualViewport?.addEventListener("resize", setAppHeight);
    window.addEventListener("resize", setAppHeight);
    window.addEventListener("orientationchange", setAppHeight);

    // Only prevent gesture zoom on iOS
    const isIOS =
      typeof navigator !== "undefined" &&
      /iPad|iPhone|iPod/.test(navigator.userAgent);

    const preventGestureZoom = (event: Event) => {
      event.preventDefault();
    };

    if (isIOS) {
      document.addEventListener("gesturestart", preventGestureZoom, {
        passive: false,
      });
      document.addEventListener("gesturechange", preventGestureZoom, {
        passive: false,
      });
      document.addEventListener("gestureend", preventGestureZoom, {
        passive: false,
      });
    }

    return () => {
      window.visualViewport?.removeEventListener("resize", setAppHeight);
      window.removeEventListener("resize", setAppHeight);
      window.removeEventListener("orientationchange", setAppHeight);
      if (isIOS) {
        document.removeEventListener("gesturestart", preventGestureZoom);
        document.removeEventListener("gesturechange", preventGestureZoom);
        document.removeEventListener("gestureend", preventGestureZoom);
      }
      root.classList.remove("app-web");
      root.style.removeProperty("--app-height");
    };
  }, []);

  if (!hydrated) {
    return (
      <AppProviders>
        {webHead}
        <StatusBar style="light" />
        <FullscreenLoader message="Preparing session..." />
      </AppProviders>
    );
  }

  return (
    <AppProviders>
      {webHead}
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
