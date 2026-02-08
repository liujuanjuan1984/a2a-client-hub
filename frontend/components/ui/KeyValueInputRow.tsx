import { View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

type KeyValueInputRowProps = {
  keyValue: string;
  valueValue: string;
  onChangeKey: (value: string) => void;
  onChangeValue: (value: string) => void;
  onRemove: () => void;
};

export function KeyValueInputRow({
  keyValue,
  valueValue,
  onChangeKey,
  onChangeValue,
  onRemove,
}: KeyValueInputRowProps) {
  return (
    <View className="flex-row gap-2">
      <Input
        className="flex-1 px-3 py-2"
        placeholder="Header"
        value={keyValue}
        onChangeText={onChangeKey}
      />
      <Input
        className="flex-1 px-3 py-2"
        placeholder="Value"
        value={valueValue}
        onChangeText={onChangeValue}
      />
      <Button label="Remove" variant="outline" size="xs" onPress={onRemove} />
    </View>
  );
}
