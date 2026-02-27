import { Ionicons } from "@expo/vector-icons";
import React, { useEffect } from "react";
import { Pressable, Text } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";

interface ExpandToggleProps {
  expanded: boolean;
  onToggle: () => void;
  label?: string;
  type?: string;
  accessibilityLabel?: string;
  testID?: string;
}

/**
 * Standardized Expand/Collapse toggle component.
 * Uses a chevron-down icon that rotates 180 degrees when expanded.
 */
export function ExpandToggle({
  expanded,
  onToggle,
  label,
  type,
  accessibilityLabel,
  testID,
}: ExpandToggleProps) {
  const rotation = useSharedValue(0);

  useEffect(() => {
    rotation.value = withSpring(expanded ? 180 : 0, {
      damping: 20,
      stiffness: 150,
    });
  }, [expanded, rotation]);

  const animatedStyle = useAnimatedStyle(() => {
    return {
      transform: [{ rotate: `${rotation.value}deg` }],
    };
  });

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
      className="flex-row items-center self-start rounded-lg px-2 py-1 active:bg-white/10"
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || displayLabel}
      testID={testID}
    >
      <Text className="text-[11px] font-medium tracking-wide text-slate-400">
        {displayLabel}
      </Text>
      <Animated.View style={[{ marginLeft: 4 }, animatedStyle]}>
        <Ionicons name="chevron-down" size={14} color="#94a3b8" />
      </Animated.View>
    </Pressable>
  );
}
