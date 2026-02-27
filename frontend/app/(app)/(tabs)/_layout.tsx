import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { Platform } from "react-native";

import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

export default function TabsLayout() {
  const insets = useAppSafeArea({ maxBottomInset: 20 });
  const fallbackBottomInset = Platform.OS === "web" ? 2 : 0;
  const tabBarBottomInset = Math.max(insets.bottom, fallbackBottomInset);
  const tabBarPaddingBottom = Math.max(tabBarBottomInset, 4);
  const tabBarHeight = 54 + tabBarPaddingBottom;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: "#FFDE03",
        tabBarInactiveTintColor: "#999999",
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: "bold",
          lineHeight: 14,
        },
        tabBarStyle: {
          backgroundColor: "#171B24",
          borderTopColor: "rgba(255, 255, 255, 0.08)",
          borderTopWidth: 1,
          height: tabBarHeight,
          minHeight: tabBarHeight,
          paddingTop: 2,
          paddingBottom: tabBarPaddingBottom,
          elevation: 0,
        },
        tabBarItemStyle: {
          minHeight: 52,
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
