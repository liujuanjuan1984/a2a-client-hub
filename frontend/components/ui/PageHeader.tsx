import { type ReactNode } from "react";
import { Text, View } from "react-native";

import {
  PAGE_HEADER_SUBTITLE_GAP,
  PAGE_HEADER_SUBTITLE_LINE_HEIGHT,
  PAGE_HEADER_TITLE_LINE_HEIGHT,
} from "@/components/layout/spacing";

type PageHeaderProps = {
  title: string;
  subtitle?: string;
  rightElement?: ReactNode;
};

export function PageHeader({ title, subtitle, rightElement }: PageHeaderProps) {
  return (
    <View className="flex-row items-start justify-between">
      <View className="flex-1 pr-4">
        <Text
          className="text-2xl font-semibold text-white"
          style={{ lineHeight: PAGE_HEADER_TITLE_LINE_HEIGHT }}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text
            className="text-sm text-muted"
            style={{
              marginTop: PAGE_HEADER_SUBTITLE_GAP,
              lineHeight: PAGE_HEADER_SUBTITLE_LINE_HEIGHT,
            }}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>
      {rightElement ? <View>{rightElement}</View> : null}
    </View>
  );
}
