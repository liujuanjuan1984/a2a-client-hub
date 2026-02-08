import { ActivityIndicator, Text, View } from "react-native";

type FullscreenLoaderProps = {
  message?: string;
};

export function FullscreenLoader({ message }: FullscreenLoaderProps) {
  return (
    <View className="flex-1 items-center justify-center bg-background">
      <ActivityIndicator size="large" color="#5c6afb" />
      {message ? (
        <Text className="mt-4 text-sm text-muted">{message}</Text>
      ) : null}
    </View>
  );
}
