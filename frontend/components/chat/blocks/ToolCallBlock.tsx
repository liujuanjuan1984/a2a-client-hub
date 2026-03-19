import React, { useCallback, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { ExpandToggle } from "@/components/ui/ExpandToggle";
import { type ChatMessage, type MessageBlock } from "@/lib/api/chat-utils";

interface ToolCallBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  messageId: string;
  messageStatus?: ChatMessage["status"];
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  isFirst?: boolean;
}

const STATUS_LABELS = {
  running: "Running",
  success: "Success",
  failed: "Failed",
  interrupted: "Interrupted",
  unknown: "Unknown",
} as const;

const STATUS_STYLES = {
  running: {
    container: "border-emerald-500/30 bg-emerald-500/10",
    text: "text-emerald-300",
  },
  success: {
    container: "border-sky-500/30 bg-sky-500/10",
    text: "text-sky-300",
  },
  failed: {
    container: "border-red-500/30 bg-red-500/10",
    text: "text-red-300",
  },
  interrupted: {
    container: "border-amber-500/30 bg-amber-500/10",
    text: "text-amber-300",
  },
  unknown: {
    container: "border-slate-500/30 bg-slate-500/10",
    text: "text-slate-300",
  },
} as const;

const deriveFallbackStatus = (
  block: MessageBlock,
  messageStatus?: ChatMessage["status"],
): keyof typeof STATUS_LABELS => {
  if (block.toolCall?.status) {
    return block.toolCall.status;
  }
  if (messageStatus === "error") {
    return "failed";
  }
  if (messageStatus === "interrupted") {
    return "interrupted";
  }
  if (messageStatus === "streaming" || !block.isFinished) {
    return "running";
  }
  if (block.isFinished) {
    return "success";
  }
  return "unknown";
};

const formatStructuredValue = (value: unknown): string | null => {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

export function ToolCallBlock({
  block,
  fallbackBlockId,
  messageId,
  messageStatus,
  onLayoutChangeStart,
  onLoadBlockContent,
  isFirst,
}: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block.content.trim();
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || fallbackBlockId;
  const toolCall = block.toolCall ?? null;
  const status = deriveFallbackStatus(block, messageStatus);
  const statusStyle = STATUS_STYLES[status];
  const statusLabel = STATUS_LABELS[status];
  const toolName = toolCall?.name?.trim() || "Tool Call";
  const argumentsText = useMemo(
    () => formatStructuredValue(toolCall?.arguments),
    [toolCall?.arguments],
  );
  const resultText = useMemo(
    () => formatStructuredValue(toolCall?.result),
    [toolCall?.result],
  );
  const errorText = useMemo(
    () => formatStructuredValue(toolCall?.error),
    [toolCall?.error],
  );

  const toggleToolCall = useCallback(() => {
    onLayoutChangeStart?.();
    setExpanded((prev) => !prev);
  }, [onLayoutChangeStart]);

  const handleToggle = async () => {
    const shouldExpand = !expanded;
    if (shouldExpand && !blockHasContent && onLoadBlockContent) {
      const loaded = await onLoadBlockContent(messageId, blockId);
      if (!loaded) {
        return;
      }
    }
    toggleToolCall();
  };

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-white/10 bg-black/40 p-3`}
    >
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1">
          <Text className="text-[12px] font-semibold tracking-wide text-white">
            {toolName}
          </Text>
          {toolCall?.callId ? (
            <Text className="mt-1 text-[10px] text-slate-500">
              call_id: {toolCall.callId}
            </Text>
          ) : null}
        </View>
        <View
          className={`rounded-full border px-2 py-1 ${statusStyle.container}`}
        >
          <Text
            className={`text-[10px] font-semibold uppercase ${statusStyle.text}`}
          >
            {statusLabel}
          </Text>
        </View>
      </View>

      {argumentsText ? (
        <Text
          numberOfLines={expanded ? undefined : 2}
          selectable={expanded}
          className="mt-2 text-[11px] leading-5 text-slate-300"
        >
          {argumentsText}
        </Text>
      ) : blockHasContent && expanded ? (
        <Text
          selectable
          className="mt-2 break-all text-[11px] leading-5 text-slate-400"
        >
          {blockText}
        </Text>
      ) : (
        <Text className="mt-2 text-[11px] italic text-slate-500">
          {expanded
            ? "Tool call detail unavailable."
            : "Tap to inspect tool call details."}
        </Text>
      )}

      {expanded && resultText ? (
        <View className="mt-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-sky-300">
            Result
          </Text>
          <Text
            selectable
            className="mt-1 text-[11px] leading-5 text-slate-300"
          >
            {resultText}
          </Text>
        </View>
      ) : null}

      {expanded && errorText ? (
        <View className="mt-3 rounded-lg border border-red-500/20 bg-red-500/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-red-300">
            Error
          </Text>
          <Text
            selectable
            className="mt-1 text-[11px] leading-5 text-slate-300"
          >
            {errorText}
          </Text>
        </View>
      ) : null}

      <View className="mt-2 items-end">
        <ExpandToggle
          expanded={expanded}
          onToggle={() => {
            handleToggle().catch(() => undefined);
          }}
          type="Tool Call"
          variant={expanded ? "mini" : "default"}
          showChevron={expanded}
          testID={`chat-message-${blockId}-tool-call-toggle`}
        />
      </View>
    </View>
  );
}
