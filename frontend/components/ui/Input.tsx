import { Text, TextInput, type TextInputProps, View } from "react-native";

interface InputProps extends TextInputProps {
  label?: string;
  error?: string;
}

export function Input({ label, error, className, ...props }: InputProps) {
  return (
    <View className="gap-1.5">
      {label ? (
        <Text className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
          {label}
        </Text>
      ) : null}
      <TextInput
        className={`rounded-xl bg-black/40 px-4 py-3 text-white ${className || ""}`}
        placeholderTextColor="#64748B"
        {...props}
      />
      {error ? (
        <Text className="text-[11px] font-bold text-red-400/80">{error}</Text>
      ) : null}
    </View>
  );
}
