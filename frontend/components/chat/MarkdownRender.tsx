import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback, useMemo } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import Markdown, { RenderRules } from "react-native-markdown-display";

import { toast } from "@/lib/toast";

interface MarkdownRenderProps {
  content: string;
  isAgent?: boolean;
}

export function MarkdownRender({ content, isAgent }: MarkdownRenderProps) {
  const handleCopyCode = useCallback(async (code: string) => {
    try {
      if (Platform.OS === "web" && typeof navigator !== "undefined") {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(code);
        } else {
          await Clipboard.setStringAsync(code);
        }
      } else {
        await Clipboard.setStringAsync(code);
      }
      toast.success("Copied", "Code copied to clipboard.");
    } catch {
      toast.error("Copy failed", "Could not copy code.");
    }
  }, []);

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
        fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
        color: "#F87171", // keep clear inline-code emphasis without a box
        fontWeight: "600",
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
        color: "#60A5FA", // blue-400
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
            <Pressable
              onPress={() => handleCopyCode(content)}
              className="p-1 hover:bg-white/10 rounded"
            >
              <Ionicons name="copy-outline" size={14} color="#94A3B8" />
            </Pressable>
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
            <Pressable
              onPress={() => handleCopyCode(content)}
              className="p-1 hover:bg-white/10 rounded"
            >
              <Ionicons name="copy-outline" size={12} color="#94A3B8" />
            </Pressable>
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
