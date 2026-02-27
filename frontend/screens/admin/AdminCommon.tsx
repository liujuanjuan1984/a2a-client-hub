import { Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";

type AdminBackHeaderProps = {
  title: string;
  subtitle: string;
  onBackPress: () => void;
};

export function AdminBackHeader({
  title,
  subtitle,
  onBackPress,
}: AdminBackHeaderProps) {
  return (
    <PageHeader
      title={title}
      subtitle={subtitle}
      rightElement={
        <IconButton
          accessibilityLabel="Go back"
          icon="chevron-back"
          size="sm"
          variant="secondary"
          onPress={onBackPress}
        />
      }
    />
  );
}

type AdminStateCardProps = {
  title: string;
  message: string;
  tone?: "error" | "neutral";
  actionLabel?: string;
  onAction?: () => void;
};

export function AdminStateCard({
  title,
  message,
  tone = "neutral",
  actionLabel,
  onAction,
}: AdminStateCardProps) {
  const isError = tone === "error";
  const containerTone = isError
    ? "border-red-500/30 bg-red-500/10"
    : "border-slate-800 bg-slate-900/30";
  const titleTone = isError ? "text-red-200" : "text-white";
  const messageTone = isError ? "text-red-100/90" : "text-muted";

  return (
    <View className={`mt-6 rounded-2xl border p-6 ${containerTone}`}>
      <Text className={`text-base font-semibold ${titleTone}`}>{title}</Text>
      <Text className={`mt-2 text-sm ${messageTone}`}>{message}</Text>
      {actionLabel && onAction ? (
        <Button
          className="mt-4 self-start"
          label={actionLabel}
          size="sm"
          variant="secondary"
          onPress={onAction}
        />
      ) : null}
    </View>
  );
}
