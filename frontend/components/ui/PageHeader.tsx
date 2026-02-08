import { type ReactNode } from "react";
import { Text, View } from "react-native";

type PageHeaderProps = {
  title: string;
  subtitle?: string;
  rightElement?: ReactNode;
};

export function PageHeader({ title, subtitle, rightElement }: PageHeaderProps) {
  return (
    <View className="flex-row items-start justify-between">
      <View className="flex-1 pr-4">
        <Text className="text-3xl font-semibold text-white">{title}</Text>
        {subtitle ? (
          <Text className="mt-2 text-base text-muted">{subtitle}</Text>
        ) : null}
      </View>
      {rightElement ? <View>{rightElement}</View> : null}
    </View>
  );
}
