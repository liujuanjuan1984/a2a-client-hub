import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import { blurActiveElement } from "@/lib/focus";

const AdminTile = ({
  title,
  subtitle,
  icon,
  onPress,
}: {
  title: string;
  subtitle: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  onPress: () => void;
}) => (
  <Pressable
    className="mb-6 border-neo border-white bg-surface shadow-neo"
    onPress={onPress}
    accessibilityRole="button"
    accessibilityLabel={title}
    accessibilityHint={subtitle}
  >
    <View className="p-5">
      <View className="flex-row items-start justify-between">
        <View className="flex-1 pr-4">
          <Text className="text-xl font-bold text-white" numberOfLines={1}>
            {title}
          </Text>
          <Text className="mt-2 text-sm font-bold text-white">{subtitle}</Text>
        </View>
        <View className="h-11 w-11 items-center justify-center border-2 border-white bg-neo-yellow">
          <Ionicons name={icon} size={20} color="#000000" />
        </View>
      </View>
    </View>
  </Pressable>
);

export function AdminHomeScreen() {
  const router = useRouter();
  const { isReady, isAdmin } = useRequireAdmin();

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <ScreenContainer>
      <PageHeader
        title="Admin"
        subtitle="System administration tools."
        rightElement={
          <IconButton
            accessibilityLabel="Go back"
            icon="chevron-back"
            size="sm"
            variant="secondary"
            onPress={() => {
              blurActiveElement();
              if (router.canGoBack()) {
                router.back();
              } else {
                router.replace("/");
              }
            }}
          />
        }
      />

      <View className="mt-4">
        <AdminTile
          title="Invitations"
          subtitle="Create and manage invitation codes."
          icon="key-outline"
          onPress={() => {
            blurActiveElement();
            router.push("/admin/invitations");
          }}
        />
        <AdminTile
          title="Shared A2A Agents"
          subtitle="Manage the global A2A service directory and allowlists."
          icon="albums-outline"
          onPress={() => {
            blurActiveElement();
            router.push("/admin/hub-a2a");
          }}
        />
      </View>
    </ScreenContainer>
  );
}
