import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { useMemo } from "react";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getWebSafeAreaInset } from "@/components/layout/safeAreaWeb";

export default function TabsLayout() {
  const insets = useSafeAreaInsets();
  const rawBottomInset =
    Platform.OS === "web" ? getWebSafeAreaInset("bottom") : insets.bottom;
  const tabBarBottomInset = Math.max(0, Math.min(rawBottomInset, 40));
  const tabBarPaddingBottom = Math.max(tabBarBottomInset, 8);
  const tabBarHeight = useMemo(
    () => 52 + tabBarPaddingBottom,
    [tabBarPaddingBottom],
  );

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: "#5c6afb",
        tabBarInactiveTintColor: "#94a3b8",
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: "600",
          lineHeight: 16,
        },
        tabBarItemStyle: {
          paddingTop: 4,
          paddingBottom: 0,
        },
        tabBarStyle: {
          backgroundColor: "#05070a",
          borderTopColor: "rgba(148, 163, 184, 0.18)",
          borderTopWidth: 1,
          height: tabBarHeight,
          paddingTop: 4,
          paddingBottom: tabBarPaddingBottom,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Agents",
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              name={focused ? "people" : "people-outline"}
              color={color}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="sessions"
        options={{
          title: "Sessions",
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              name={focused ? "chatbubbles" : "chatbubbles-outline"}
              color={color}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="scheduled-jobs"
        options={{
          title: "Jobs",
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              name={focused ? "calendar" : "calendar-outline"}
              color={color}
              size={size}
            />
          ),
        }}
      />
    </Tabs>
  );
}
