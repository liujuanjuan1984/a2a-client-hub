import React, { lazy, Suspense } from "react";
import { Text, View } from "react-native";

const LazyMarkdownComponent = lazy(async () => {
  const module = await import("./MarkdownRender");
  return { default: module.MarkdownRender };
});

export function LazyMarkdownRender({
  content,
  isAgent = false,
}: {
  content: string;
  isAgent?: boolean;
}) {
  const fallbackTone = isAgent ? "text-slate-200" : "text-white";

  return (
    <Suspense
      fallback={
        <View className="flex-1">
          <Text
            className={`text-sm leading-6 whitespace-pre-wrap ${fallbackTone}`}
          >
            {content}
          </Text>
        </View>
      }
    >
      <LazyMarkdownComponent content={content} isAgent={isAgent} />
    </Suspense>
  );
}
