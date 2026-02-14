import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { Platform } from "react-native";

import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

export default function TabsLayout() {
  const insets = useAppSafeArea({ maxBottomInset: 40 });
  const fallbackBottomInset = Platform.OS === "web" ? 16 : 0;
  const tabBarBottomInset = Math.max(insets.bottom, fallbackBottomInset);
  const tabBarPaddingBottom = Math.max(tabBarBottomInset, 8);

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
        tabBarStyle: {
          backgroundColor: "#05070a",
          borderTopColor: "rgba(148, 163, 184, 0.18)",
          borderTopWidth: 1,
          minHeight: 58 + tabBarPaddingBottom,
          paddingTop: 0,
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
