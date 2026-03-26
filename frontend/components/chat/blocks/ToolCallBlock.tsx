import React, { useCallback, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { ExpandToggle } from "@/components/ui/ExpandToggle";
import {
  type ChatMessage,
  type MessageBlock,
  type ToolCallDetailView,
  type ToolCallTimelineEntry,
} from "@/lib/api/chat-utils";

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
  completed: "Completed",
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
  completed: {
    container: "border-sky-500/30 bg-sky-500/10",
    text: "text-sky-300",
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

const TIMELINE_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  success: "Success",
  failed: "Failed",
  interrupted: "Interrupted",
  cancelled: "Cancelled",
  canceled: "Cancelled",
  unknown: "Unknown",
};

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
    return "completed";
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

const formatTimelineStatusLabel = (status: string): string => {
  const normalized = status.trim().toLowerCase();
  if (normalized in TIMELINE_STATUS_LABELS) {
    return TIMELINE_STATUS_LABELS[normalized];
  }
  if (!normalized) {
    return "Unknown";
  }
  return normalized
    .split(/[_-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const hasLoadedToolCallDetail = (toolCallDetail?: ToolCallDetailView | null) =>
  Boolean(toolCallDetail);

const extractCommandMetadata = (value: unknown) => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {
      command: null,
      metadata: value,
    };
  }
  const command =
    typeof (value as { command?: unknown }).command === "string"
      ? (value as { command: string }).command.trim()
      : "";
  const metadataEntries = Object.entries(
    value as Record<string, unknown>,
  ).filter(([key]) => key !== "command");
  return {
    command: command.length > 0 ? command : null,
    metadata:
      metadataEntries.length > 0 ? Object.fromEntries(metadataEntries) : null,
  };
};

function DetailCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <View className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5">
      <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </Text>
      <View className="mt-2">{children}</View>
    </View>
  );
}

function StatusBadge({
  statusLabel,
  statusStyle,
}: {
  statusLabel: string;
  statusStyle: (typeof STATUS_STYLES)[keyof typeof STATUS_STYLES];
}) {
  return (
    <View className={`rounded-full border px-2 py-1 ${statusStyle.container}`}>
      <Text
        className={`text-[10px] font-semibold uppercase ${statusStyle.text}`}
      >
        {statusLabel}
      </Text>
    </View>
  );
}

function StructuredValueBlock({
  value,
  tone = "text-slate-300",
}: {
  value: unknown;
  tone?: string;
}) {
  const text = formatStructuredValue(value);
  if (!text) {
    return null;
  }
  return (
    <Text selectable className={`text-[11px] leading-5 ${tone}`}>
      {text}
    </Text>
  );
}

function TimelineEntryCard({ entry }: { entry: ToolCallTimelineEntry }) {
  const title =
    typeof entry.title === "string" && entry.title.trim().length > 0
      ? entry.title.trim()
      : null;
  return (
    <View className="rounded-lg border border-white/10 bg-black/20 p-2.5">
      <View className="flex-row items-center justify-between gap-3">
        <Text className="text-[11px] font-semibold text-white">
          {formatTimelineStatusLabel(entry.status)}
        </Text>
        {title ? (
          <Text className="flex-1 text-right text-[10px] text-slate-400">
            {title}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

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
  const [showRaw, setShowRaw] = useState(false);

  const blockText = block.content.trim();
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || fallbackBlockId;
  const toolCall = block.toolCall ?? null;
  const toolCallDetail = block.toolCallDetail ?? null;
  const resolvedToolCall = toolCallDetail ?? toolCall;
  const status = deriveFallbackStatus(block, messageStatus);
  const statusStyle = STATUS_STYLES[status];
  const statusLabel = STATUS_LABELS[status];
  const toolName = resolvedToolCall?.name?.trim() || "Tool Call";
  const collapsedLabel = `Show Tool Call ${statusLabel}`;
  const titleText =
    typeof toolCallDetail?.title === "string" &&
    toolCallDetail.title.trim().length > 0
      ? toolCallDetail.title.trim()
      : null;
  const timeline = useMemo(
    () =>
      Array.isArray(toolCallDetail?.timeline) ? toolCallDetail.timeline : [],
    [toolCallDetail?.timeline],
  );
  const argumentsText = useMemo(
    () => formatStructuredValue(resolvedToolCall?.arguments),
    [resolvedToolCall?.arguments],
  );
  const resultText = useMemo(
    () => formatStructuredValue(resolvedToolCall?.result),
    [resolvedToolCall?.result],
  );
  const errorText = useMemo(
    () => formatStructuredValue(resolvedToolCall?.error),
    [resolvedToolCall?.error],
  );
  const rawText = useMemo(
    () => formatStructuredValue(toolCallDetail?.raw ?? (blockText || null)),
    [blockText, toolCallDetail?.raw],
  );
  const { command, metadata } = useMemo(
    () => extractCommandMetadata(resolvedToolCall?.arguments),
    [resolvedToolCall?.arguments],
  );

  const toggleToolCall = useCallback(() => {
    onLayoutChangeStart?.();
    setExpanded((prev) => !prev);
  }, [onLayoutChangeStart]);

  const handleToggle = async () => {
    const shouldExpand = !expanded;
    if (!shouldExpand) {
      setShowRaw(false);
    }
    const shouldLoadDetail =
      shouldExpand &&
      block.isFinished &&
      onLoadBlockContent &&
      !hasLoadedToolCallDetail(toolCallDetail);
    if (shouldLoadDetail) {
      const loaded = await onLoadBlockContent(messageId, blockId);
      if (!loaded && !blockHasContent) {
        return;
      }
    } else if (shouldExpand && !blockHasContent && onLoadBlockContent) {
      const loaded = await onLoadBlockContent(messageId, blockId);
      if (!loaded) {
        return;
      }
    }
    toggleToolCall();
  };

  if (!expanded) {
    return (
      <View
        key={blockId}
        className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-white/10 bg-black/40 p-3`}
      >
        <View className="flex-row items-center justify-between gap-3">
          <ExpandToggle
            expanded={expanded}
            onToggle={() => {
              handleToggle().catch(() => undefined);
            }}
            type="Tool Call"
            accessibilityLabel={collapsedLabel}
            testID={`chat-message-${blockId}-tool-call-toggle`}
          />
          <StatusBadge statusLabel={statusLabel} statusStyle={statusStyle} />
        </View>
      </View>
    );
  }

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
          {titleText ? (
            <Text className="mt-1 text-[11px] text-slate-300">{titleText}</Text>
          ) : null}
          {resolvedToolCall?.callId ? (
            <Text className="mt-1 text-[10px] text-slate-500">
              call_id: {resolvedToolCall.callId}
            </Text>
          ) : null}
        </View>
        <StatusBadge statusLabel={statusLabel} statusStyle={statusStyle} />
      </View>

      {command || argumentsText ? (
        <DetailCard label="Input">
          {command ? (
            <View className="rounded-lg border border-white/10 bg-black/30 p-2.5">
              <Text className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                Command
              </Text>
              <Text selectable className="text-[11px] leading-5 text-slate-200">
                {command}
              </Text>
            </View>
          ) : null}
          {metadata ? (
            <View className={command ? "mt-2" : ""}>
              <StructuredValueBlock value={metadata} />
            </View>
          ) : !command && argumentsText ? (
            <StructuredValueBlock value={resolvedToolCall?.arguments} />
          ) : null}
        </DetailCard>
      ) : null}

      {block.isFinished && timeline.length > 0 ? (
        <DetailCard label="Progress">
          <View className="gap-2">
            {timeline.map((entry, index) => (
              <TimelineEntryCard
                key={`${blockId}-timeline-${index}-${entry.status}`}
                entry={entry}
              />
            ))}
          </View>
        </DetailCard>
      ) : null}

      {resultText ? (
        <DetailCard label="Result">
          <StructuredValueBlock value={resolvedToolCall?.result} />
        </DetailCard>
      ) : null}

      {errorText ? (
        <DetailCard label="Error">
          <StructuredValueBlock
            value={resolvedToolCall?.error}
            tone="text-red-200"
          />
        </DetailCard>
      ) : null}

      {!block.isFinished && !argumentsText && !resultText && !errorText ? (
        <Text className="mt-3 text-[11px] italic text-slate-500">
          Tool call is still running.
        </Text>
      ) : null}

      {!command &&
      !argumentsText &&
      !resultText &&
      !errorText &&
      timeline.length === 0 &&
      !rawText ? (
        <Text className="mt-3 text-[11px] italic text-slate-500">
          Tool call detail unavailable.
        </Text>
      ) : null}

      <View className="mt-3 flex-row items-center justify-between border-t border-white/5 pt-2">
        <ExpandToggle
          expanded={expanded}
          onToggle={() => {
            handleToggle().catch(() => undefined);
          }}
          type="Tool Call"
          variant="mini"
          showChevron={expanded}
          testID={`chat-message-${blockId}-tool-call-toggle`}
        />
        {rawText ? (
          <ExpandToggle
            expanded={showRaw}
            onToggle={() => {
              setShowRaw((prev) => !prev);
            }}
            type="Raw Payload"
            variant="mini"
            showChevron
            testID={`chat-message-${blockId}-tool-call-raw-toggle`}
          />
        ) : (
          <View />
        )}
      </View>
      {rawText && showRaw ? (
        <View className="mt-2 rounded-lg border border-white/10 bg-black/30 p-2.5">
          <Text selectable className="text-[11px] leading-5 text-slate-400">
            {rawText}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
