import { useRouter } from "expo-router";

import { IconButton } from "@/components/ui/IconButton";
import { blurActiveElement } from "@/lib/focus";

export function AccountEntryButton() {
  const router = useRouter();

  return (
    <IconButton
      accessibilityLabel="Open account security"
      icon="person-circle-outline"
      size="sm"
      variant="secondary"
      onPress={() => {
        blurActiveElement();
        router.push("/account");
      }}
    />
  );
}
