import React, { useMemo } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";
import Markdown, { RenderRules } from "react-native-markdown-display";

import { CopyButton } from "../ui/CopyButton";

import { chatMarkdownPalette } from "@/theme/colors";

interface MarkdownRenderProps {
  content: string;
  isAgent?: boolean;
}

export function MarkdownRender({ content, isAgent }: MarkdownRenderProps) {
  const styles = useMemo(() => {
    const baseTextColor = isAgent
      ? chatMarkdownPalette.agentText
      : chatMarkdownPalette.userText;
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
        backgroundColor: chatMarkdownPalette.inlineCodeBackground,
        borderRadius: 4,
        borderWidth: 0,
        paddingHorizontal: 4,
        paddingVertical: 2,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: chatMarkdownPalette.inlineCodeText,
      },
      strong: {
        color: chatMarkdownPalette.strongText,
        fontWeight: "bold",
      },
      em: {
        color: chatMarkdownPalette.emphasisText,
        fontStyle: "italic",
      },
      code_block: {
        backgroundColor: chatMarkdownPalette.codeBackground,
        borderRadius: 8,
        padding: 12,
        marginVertical: 8,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: chatMarkdownPalette.codeText,
      },
      fence: {
        backgroundColor: chatMarkdownPalette.codeBackground,
        borderRadius: 8,
        padding: 12,
        marginVertical: 8,
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: chatMarkdownPalette.codeText,
      },
      link: {
        color: chatMarkdownPalette.linkText,
        textDecorationLine: "underline",
      },
      bullet_list: {
        marginBottom: 8,
      },
      ordered_list: {
        marginBottom: 8,
      },
      blockquote: {
        backgroundColor: chatMarkdownPalette.blockquoteBackground,
        borderLeftColor: chatMarkdownPalette.blockquoteBorder,
        borderLeftWidth: 4,
        paddingLeft: 12,
        paddingVertical: 4,
        marginVertical: 8,
        borderRadius: 4,
      },
      hr: {
        backgroundColor: chatMarkdownPalette.divider,
        borderRadius: 999,
        height: StyleSheet.hairlineWidth || 1,
        marginVertical: 16,
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
              iconColor={chatMarkdownPalette.chromeMuted}
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
              iconColor={chatMarkdownPalette.chromeMuted}
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
