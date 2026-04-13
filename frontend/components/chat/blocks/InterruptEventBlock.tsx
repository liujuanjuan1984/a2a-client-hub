import React from "react";
import { Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface InterruptEventBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  isFirst?: boolean;
}

const BADGE_STYLES = {
  actionRequired: {
    container: "border-amber-500/30 bg-amber-500/10",
    text: "text-amber-200",
    label: "Action Required",
  },
  handled: {
    container: "border-emerald-500/30 bg-emerald-500/10",
    text: "text-emerald-200",
    label: "Handled",
  },
  rejected: {
    container: "border-rose-500/30 bg-rose-500/10",
    text: "text-rose-200",
    label: "Rejected",
  },
  expired: {
    container: "border-slate-400/30 bg-slate-500/10",
    text: "text-slate-200",
    label: "Expired",
  },
} as const;

const resolveBadgeTone = (block: MessageBlock): keyof typeof BADGE_STYLES => {
  const interrupt = block.interrupt;
  if (!interrupt) {
    return "actionRequired";
  }
  if (interrupt.phase === "resolved" && interrupt.resolution === "expired") {
    return "expired";
  }
  if (interrupt.phase === "resolved" && interrupt.resolution === "rejected") {
    return "rejected";
  }
  if (interrupt.phase === "resolved") {
    return "handled";
  }
  return "actionRequired";
};

const resolveInterruptTitle = (block: MessageBlock): string => {
  const interrupt = block.interrupt;
  if (!interrupt) {
    return "Interrupt";
  }
  if (interrupt.phase === "resolved") {
    if (interrupt.type === "permission") {
      return "Authorization update";
    }
    if (interrupt.type === "permissions") {
      return "Permissions update";
    }
    if (interrupt.type === "elicitation") {
      return "Structured input update";
    }
    return "Question update";
  }
  if (interrupt.type === "permission") {
    return "Authorization requested";
  }
  if (interrupt.type === "permissions") {
    return "Permissions approval requested";
  }
  if (interrupt.type === "elicitation") {
    return "Structured input requested";
  }
  return "Additional input requested";
};

export function InterruptEventBlock({
  block,
  fallbackBlockId,
  isFirst,
}: InterruptEventBlockProps) {
  const blockText = block.content.trim();
  const blockId = block.id || fallbackBlockId;
  const interrupt = block.interrupt;

  if (!blockText && !interrupt) {
    return null;
  }

  const badgeTone = resolveBadgeTone(block);
  const badge = BADGE_STYLES[badgeTone];
  const patterns =
    interrupt?.phase === "asked" && interrupt.type === "permission"
      ? (interrupt.details.patterns ?? [])
      : [];
  const questions =
    interrupt?.phase === "asked" && interrupt.type === "question"
      ? (interrupt.details.questions ?? [])
      : [];
  const requestedPermissions =
    interrupt?.phase === "asked" && interrupt.type === "permissions"
      ? (() => {
          try {
            return JSON.stringify(interrupt.details.permissions ?? {}, null, 2);
          } catch {
            return null;
          }
        })()
      : null;
  const requestedSchema =
    interrupt?.phase === "asked" && interrupt.type === "elicitation"
      ? (() => {
          try {
            return JSON.stringify(
              interrupt.details.requestedSchema ?? {},
              null,
              2,
            );
          } catch {
            return null;
          }
        })()
      : null;

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-amber-500/30 bg-amber-500/10 p-3`}
    >
      <View className="flex-row items-center justify-between gap-3">
        <View className="min-w-0 flex-1">
          <Text className="text-[11px] font-medium uppercase tracking-wide text-amber-200">
            Interrupt
          </Text>
          <Text className="mt-1 text-[13px] font-semibold text-amber-50">
            {resolveInterruptTitle(block)}
          </Text>
        </View>
        <View className={`rounded-full border px-2 py-1 ${badge.container}`}>
          <Text className={`text-[10px] font-semibold uppercase ${badge.text}`}>
            {badge.label}
          </Text>
        </View>
      </View>

      {blockText ? (
        <Text
          selectable
          className="mt-2 text-[12px] font-normal leading-5 text-amber-50"
        >
          {blockText}
        </Text>
      ) : null}

      {interrupt?.phase === "asked" && interrupt.type === "permission" ? (
        <View className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Permission
          </Text>
          <Text className="mt-2 text-[12px] leading-5 text-slate-100">
            {interrupt.details.permission ?? "unknown"}
          </Text>
          {patterns.length > 0 ? (
            <Text className="mt-2 text-[11px] leading-5 text-slate-300">
              Targets: {patterns.join(", ")}
            </Text>
          ) : null}
        </View>
      ) : null}

      {interrupt?.phase === "asked" && interrupt.type === "question" ? (
        <View className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Questions
          </Text>
          {questions.map((question, index) => (
            <View
              key={`${interrupt.requestId}:${index}:${question.question}`}
              className={index === 0 ? "mt-2" : "mt-3"}
            >
              {question.header ? (
                <Text className="text-[11px] font-semibold text-slate-200">
                  {question.header}
                </Text>
              ) : null}
              <Text className="mt-1 text-[12px] leading-5 text-slate-100">
                {question.question}
              </Text>
              {question.description ? (
                <Text className="mt-1 text-[11px] leading-5 text-slate-300">
                  {question.description}
                </Text>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}

      {interrupt?.phase === "asked" && interrupt.type === "permissions" ? (
        <View className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Requested Permissions
          </Text>
          {requestedPermissions ? (
            <Text className="mt-2 font-mono text-[11px] leading-5 text-slate-100">
              {requestedPermissions}
            </Text>
          ) : (
            <Text className="mt-2 text-[12px] leading-5 text-slate-100">
              No structured permissions payload was provided.
            </Text>
          )}
        </View>
      ) : null}

      {interrupt?.phase === "asked" && interrupt.type === "elicitation" ? (
        <View className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5">
          <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Elicitation
          </Text>
          {interrupt.details.mode ? (
            <Text className="mt-2 text-[12px] leading-5 text-slate-100">
              Mode: {interrupt.details.mode}
            </Text>
          ) : null}
          {interrupt.details.serverName ? (
            <Text className="mt-1 text-[12px] leading-5 text-slate-100">
              Server: {interrupt.details.serverName}
            </Text>
          ) : null}
          {interrupt.details.url ? (
            <Text className="mt-1 text-[12px] leading-5 text-slate-100">
              URL: {interrupt.details.url}
            </Text>
          ) : null}
          {requestedSchema ? (
            <>
              <Text className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Requested Schema
              </Text>
              <Text className="mt-1 font-mono text-[11px] leading-5 text-slate-100">
                {requestedSchema}
              </Text>
            </>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
