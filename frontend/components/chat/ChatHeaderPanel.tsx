import Ionicons from "@expo/vector-icons/Ionicons";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { BackButton } from "@/components/ui/BackButton";
import { Button } from "@/components/ui/Button";
import { type AgentSession } from "@/lib/chat-utils";
import { type AgentConfig } from "@/store/agents";

type CapabilityStatus = "unknown" | "supported" | "unsupported";

const INFO_CARD_CLASS =
  "min-w-[46%] flex-1 rounded-xl border border-white/5 bg-black/20 px-3 py-2.5";

const resolveModesValue = (session?: AgentSession) => {
  const inputModes =
    session?.inputModes?.filter((mode) => Boolean(mode?.trim())) ?? [];
  const outputModes =
    session?.outputModes?.filter((mode) => Boolean(mode?.trim())) ?? [];
  if (inputModes.length === 0 && outputModes.length === 0) {
    return null;
  }
  const inputValue = inputModes.length > 0 ? inputModes.join(", ") : "N/A";
  const outputValue = outputModes.length > 0 ? outputModes.join(", ") : "N/A";
  return `${inputValue} -> ${outputValue}`;
};

const InfoCard = ({ label, value }: { label: string; value: string }) => (
  <View className={INFO_CARD_CLASS}>
    <Text
      className="text-[10px] font-medium uppercase tracking-wider text-slate-500"
      numberOfLines={1}
    >
      {label}
    </Text>
    <Text
      className="mt-1 text-[11px] font-normal leading-4 text-slate-300"
      numberOfLines={1}
    >
      {value}
    </Text>
  </View>
);

export function ChatHeaderPanel({
  topInset,
  agent,
  conversationId,
  sessionSource,
  session,
  showDetails,
  onToggleDetails,
  onOpenSessionPicker,
  onTestConnection,
  testingConnection,
  modelSelectionStatus,
  providerDiscoveryStatus,
  interruptRecoveryStatus,
  sessionPromptAsyncStatus,
  sessionAppendStatus,
  sessionCommandStatus,
  sessionShellStatus,
  invokeMetadataStatus,
}: {
  topInset: number;
  agent: AgentConfig;
  conversationId?: string;
  sessionSource: "manual" | "scheduled" | null;
  session?: AgentSession;
  showDetails: boolean;
  onToggleDetails: () => void;
  onOpenSessionPicker: () => void;
  onTestConnection: () => void;
  testingConnection: boolean;
  modelSelectionStatus: CapabilityStatus;
  providerDiscoveryStatus: CapabilityStatus;
  interruptRecoveryStatus: CapabilityStatus;
  sessionPromptAsyncStatus: CapabilityStatus;
  sessionAppendStatus: CapabilityStatus;
  sessionCommandStatus: CapabilityStatus;
  sessionShellStatus: CapabilityStatus;
  invokeMetadataStatus: CapabilityStatus;
}) {
  const workingDirectory = session?.workingDirectory?.trim() || null;
  const modesValue = resolveModesValue(session);
  const capabilityItems = [
    { label: "Model Selection", status: modelSelectionStatus },
    { label: "Provider Discovery", status: providerDiscoveryStatus },
    { label: "Interrupt Recovery", status: interruptRecoveryStatus },
    { label: "Prompt Async", status: sessionPromptAsyncStatus },
    { label: "Streaming Append", status: sessionAppendStatus },
    { label: "Session Command", status: sessionCommandStatus },
    { label: "Session Shell", status: sessionShellStatus },
    { label: "Invoke Metadata", status: invokeMetadataStatus },
  ];
  const availableCapabilities = capabilityItems
    .filter((item) => item.status === "supported")
    .map((item) => item.label);

  return (
    <View
      className="border-b border-white/5 bg-background px-2 sm:px-6 pb-4"
      style={{ paddingTop: topInset }}
    >
      <View className="flex-row items-center justify-between">
        <View className="flex-1 flex-row items-center gap-2">
          <View>
            <Text className="text-base font-bold text-white" numberOfLines={1}>
              {agent.name}
            </Text>
          </View>
        </View>
        <View className="flex-row items-center gap-2">
          <BackButton />
          <Pressable
            className="h-10 w-10 items-center justify-center rounded-xl bg-primary"
            onPress={onOpenSessionPicker}
            accessibilityRole="button"
            accessibilityLabel="Show sessions"
            accessibilityHint="View and switch chat sessions"
          >
            <Ionicons name="list" size={20} color="#000000" />
          </Pressable>
          <Pressable
            className={`h-10 w-10 items-center justify-center rounded-xl ${
              showDetails ? "bg-primary" : "bg-slate-800"
            }`}
            onPress={onToggleDetails}
            accessibilityRole="button"
            accessibilityLabel="Toggle details"
            accessibilityHint="Show or hide session details"
          >
            <Ionicons
              name={
                showDetails
                  ? "information-circle"
                  : "information-circle-outline"
              }
              size={20}
              color={showDetails ? "#000000" : "#FFFFFF"}
            />
          </Pressable>
        </View>
      </View>

      {showDetails ? (
        <View className="mt-4 gap-3 overflow-hidden rounded-2xl bg-surface p-4 shadow-sm">
          <View className="flex-row items-center gap-3">
            <InfoCard label="Agent Card" value={agent.cardUrl} />
            <Button
              label="Check"
              size="xs"
              variant="secondary"
              iconLeft="pulse-outline"
              loading={testingConnection}
              onPress={onTestConnection}
            />
          </View>

          <View className="flex-row flex-wrap gap-3">
            <InfoCard label="Conversation ID" value={conversationId ?? "N/A"} />
            <InfoCard label="Source" value={sessionSource ?? "N/A"} />
            {session?.runtimeStatus ? (
              <InfoCard label="Runtime" value={session.runtimeStatus} />
            ) : null}
            <InfoCard label="Transport" value={session?.transport ?? "N/A"} />
            {modesValue ? <InfoCard label="Modes" value={modesValue} /> : null}
            {workingDirectory ? (
              <InfoCard label="Working Directory" value={workingDirectory} />
            ) : null}
          </View>

          {availableCapabilities.length > 0 ? (
            <View>
              <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Capabilities
              </Text>
              <View className="mt-2 flex-row flex-wrap gap-2">
                {availableCapabilities.map((label) => (
                  <View
                    key={label}
                    className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5"
                  >
                    <Text className="text-[10px] font-medium text-emerald-200">
                      {label}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          {session?.externalSessionRef?.externalSessionId ? (
            <>
              <View className="h-[1px] bg-slate-800" />
              <Text className="text-xs text-muted">
                External history is shown inline in this chat.
              </Text>
            </>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
