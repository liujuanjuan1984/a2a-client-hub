import React, { useMemo } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";
import Markdown, { RenderRules } from "react-native-markdown-display";

import { CopyButton } from "../ui/CopyButton";

interface MarkdownRenderProps {
  content: string;
  isAgent?: boolean;
}

export function MarkdownRender({ content, isAgent }: MarkdownRenderProps) {
  const styles = useMemo(() => {
    const baseTextColor = isAgent ? "#E2E8F0" : "#FFFFFF"; // slate-200 or white
    return StyleSheet.create({
      body: {
        fontSize: 14,
        lineHeight: 24,
        color: baseTextColor,
      },
      paragraph: {
        marginTop: 0,
        marginBottom: 8,
      },
      heading1: {
        color: baseTextColor,
        marginTop: 12,
        marginBottom: 8,
        fontWeight: "bold",
        fontSize: 20,
      },
      heading2: {
        color: baseTextColor,
        marginTop: 12,
        marginBottom: 8,
        fontWeight: "bold",
        fontSize: 18,
      },
      heading3: {
        color: baseTextColor,
        marginTop: 12,
        marginBottom: 8,
        fontWeight: "bold",
        fontSize: 16,
      },
      code_inline: {
        backgroundColor: "rgba(0, 0, 0, 0.2)",
        borderRadius: 4,
        borderWidth: 0,
        paddingHorizontal: 4,
        paddingVertical: 2,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: "rgba(52, 211, 153, 0.8)", // emerald-400 at 80% opacity
      },
      strong: {
        color: "rgba(251, 191, 36, 0.8)", // amber-400 at 80% opacity
        fontWeight: "bold",
      },
      em: {
        color: "rgba(167, 139, 250, 0.8)", // violet-400 at 80% opacity
        fontStyle: "italic",
      },
      code_block: {
        backgroundColor: "rgba(0, 0, 0, 0.5)",
        borderRadius: 8,
        padding: 12,
        marginVertical: 8,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: "#F1F5F9", // slate-100
      },
      fence: {
        backgroundColor: "rgba(0, 0, 0, 0.5)",
        borderRadius: 8,
        padding: 12,
        marginVertical: 8,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: "#F1F5F9",
      },
      link: {
        color: "rgba(56, 189, 248, 0.8)", // sky-400 at 80% opacity
        textDecorationLine: "underline",
      },
      bullet_list: {
        marginBottom: 8,
      },
      ordered_list: {
        marginBottom: 8,
      },
      blockquote: {
        backgroundColor: "rgba(255, 255, 255, 0.1)",
        borderLeftColor: "#94A3B8",
        borderLeftWidth: 4,
        paddingLeft: 12,
        paddingVertical: 4,
        marginVertical: 8,
        borderRadius: 4,
      },
    });
  }, [isAgent]);

  const rules: RenderRules = {
    fence: (node, children, parent, styles) => {
      const { content } = node;
      return (
        <View key={node.key} style={styles.fence}>
          <View className="flex-row justify-between items-center mb-2 border-b border-white/10 pb-1">
            <Text className="text-[10px] text-slate-400 font-bold uppercase tracking-widest">
              {(node as any).sourceInfo || "Code"}
            </Text>
            <CopyButton
              value={content}
              successMessage="Code copied to clipboard."
              errorMessage="Could not copy code."
              accessibilityLabel="Copy code block"
              variant="ghost"
              size="xs"
              iconSize={14}
              iconColor="#94A3B8"
              className="h-6 w-6 rounded-md"
            />
          </View>
          <Text style={styles.code_block}>{content.trim()}</Text>
        </View>
      );
    },
    code_block: (node, children, parent, styles) => {
      const { content } = node;
      return (
        <View key={node.key} style={styles.code_block}>
          <View className="flex-row justify-end mb-1">
            <CopyButton
              value={content}
              successMessage="Code copied to clipboard."
              errorMessage="Could not copy code."
              accessibilityLabel="Copy code block"
              variant="ghost"
              size="xs"
              iconSize={12}
              iconColor="#94A3B8"
              className="h-5 w-5 rounded"
            />
          </View>
          <Text style={styles.code_block}>{content.trim()}</Text>
        </View>
      );
    },
  };

  return (
    <View className="flex-1">
      <Markdown style={styles} rules={rules}>
        {content}
      </Markdown>
    </View>
  );
}
