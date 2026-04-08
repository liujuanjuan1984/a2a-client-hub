import Ionicons from "@expo/vector-icons/Ionicons";
import React from "react";
import { Pressable, Text, View } from "react-native";

interface ExpandToggleProps {
  expanded: boolean;
  onToggle: () => void;
  label?: string;
  type?: string;
  accessibilityLabel?: string;
  testID?: string;
  showChevron?: boolean;
  variant?: "default" | "mini";
}

function ExpandToggleChevron({
  expanded,
  mini,
}: {
  expanded: boolean;
  mini?: boolean;
}) {
  return (
    <View
      style={{
        marginLeft: mini ? 2 : 4,
        transform: [{ rotate: expanded ? "180deg" : "0deg" }],
      }}
    >
      <Ionicons
        name="chevron-down"
        size={mini ? 10 : 14}
        color={mini ? "#64748b" : "#94a3b8"}
      />
    </View>
  );
}

/**
 * Standardized Expand/Collapse toggle component.
 */
export function ExpandToggle({
  expanded,
  onToggle,
  label,
  type,
  accessibilityLabel,
  testID,
  showChevron = true,
  variant = "default",
}: ExpandToggleProps) {
  const isMini = variant === "mini";
  // Standard labels per issue requirements:
  // 1. Technical/Logic block: Show [Type] / Hide [Type]
  // 2. Normal text: Show more / Show less
  const displayLabel =
    label ||
    (type
      ? `${expanded ? "Hide" : "Show"} ${type}`
      : expanded
        ? "Show less"
        : "Show more");

  return (
    <Pressable
      onPress={onToggle}
      className={`flex-row items-center self-start ${
        isMini ? "" : "rounded-lg px-2 py-1 active:bg-white/10"
      }`}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || displayLabel}
      testID={testID}
    >
      <Text
        className={`${
          isMini ? "text-[10px] text-slate-500" : "text-[11px] text-slate-400"
        } font-medium tracking-wide`}
      >
        {displayLabel}
      </Text>
      {showChevron ? (
        <ExpandToggleChevron expanded={expanded} mini={isMini} />
      ) : null}
    </Pressable>
  );
}
