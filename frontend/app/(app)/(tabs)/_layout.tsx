import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { Platform } from "react-native";

import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

export default function TabsLayout() {
  const insets = useAppSafeArea({ maxBottomInset: 40 });
  const fallbackBottomInset = Platform.OS === "web" ? 16 : 0;
  const tabBarBottomInset = Math.max(insets.bottom, fallbackBottomInset);
  const tabBarPaddingBottom = Math.max(tabBarBottomInset, 8);
  const tabBarHeight = 58 + tabBarPaddingBottom;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: "#000000",
        tabBarInactiveTintColor: "#666666",
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: "bold",
          lineHeight: 16,
        },
        tabBarStyle: {
          backgroundColor: "#FFFFFF",
          borderTopColor: "#000000",
          borderTopWidth: 2,
          height: tabBarHeight,
          minHeight: tabBarHeight,
          paddingTop: 0,
          paddingBottom: tabBarPaddingBottom,
          elevation: 0,
        },
        tabBarItemStyle: {
          minHeight: 56,
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
