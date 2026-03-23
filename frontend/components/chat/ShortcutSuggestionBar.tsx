import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

export interface ShortcutSuggestionItem {
  id: string;
  title: string;
  prompt: string;
}

export function ShortcutSuggestionBar({
  shortcuts,
  onUseShortcut,
}: {
  shortcuts: ShortcutSuggestionItem[];
  onUseShortcut: (prompt: string) => void;
}) {
  if (shortcuts.length === 0) {
    return null;
  }

  return (
    <View className="mb-3">
      <Text className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        Quick Suggestions
      </Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingRight: 8 }}
        keyboardShouldPersistTaps="handled"
      >
        {shortcuts.map((shortcut, index) => (
          <Pressable
            key={shortcut.id}
            className={`rounded-full border border-white/10 bg-black/25 px-3 py-2 ${
              index > 0 ? "ml-2" : ""
            }`}
            accessibilityRole="button"
            accessibilityLabel={`Use shortcut ${shortcut.title}`}
            onPress={() => onUseShortcut(shortcut.prompt)}
          >
            <Text
              className="max-w-[180px] text-[12px] font-medium text-slate-200"
              numberOfLines={1}
            >
              {shortcut.title}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}
