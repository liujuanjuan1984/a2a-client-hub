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
  showChevron?: boolean;
}

function ExpandToggleChevron({ expanded }: { expanded: boolean }) {
  const rotation = useSharedValue(expanded ? 180 : 0);

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

  return (
    <Animated.View style={[{ marginLeft: 4 }, animatedStyle]}>
      <Ionicons name="chevron-down" size={14} color="#94a3b8" />
    </Animated.View>
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
}: ExpandToggleProps) {
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
      {showChevron ? <ExpandToggleChevron expanded={expanded} /> : null}
    </Pressable>
  );
}
