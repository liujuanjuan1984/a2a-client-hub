import { Text, TextInput, type TextInputProps, View } from "react-native";

interface InputProps extends TextInputProps {
  label?: string;
  error?: string;
}

export function Input({ label, error, className, ...props }: InputProps) {
  return (
    <View className="gap-2">
      {label ? (
        <Text className="text-sm font-medium text-white">{label}</Text>
      ) : null}
      <TextInput
        className={`rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-white ${className || ""}`}
        placeholderTextColor="#6b7280"
        {...props}
      />
      {error ? <Text className="text-xs text-red-400">{error}</Text> : null}
    </View>
  );
}
