import Ionicons from "@expo/vector-icons/Ionicons";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { BackButton } from "@/components/ui/BackButton";
import { Button } from "@/components/ui/Button";
import { type AgentSession } from "@/lib/chat-utils";
import { getOpencodeDirectory } from "@/lib/opencodeMetadata";
import { type AgentConfig } from "@/store/agents";

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
}) {
  const workingDirectory = getOpencodeDirectory(session?.metadata);

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
        <View className="mt-4 gap-4 overflow-hidden rounded-2xl bg-surface p-5 shadow-sm">
          <View>
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Agent Endpoint
            </Text>
            <Text className="mt-1 break-all text-[11px] font-normal text-slate-300">
              {agent.cardUrl}
            </Text>
          </View>

          <View className="h-[1px] bg-white/5" />

          <View className="flex-row flex-wrap gap-4">
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Conversation ID
              </Text>
              <Text
                className="mt-1 text-[11px] font-normal text-slate-300"
                numberOfLines={1}
              >
                {conversationId ?? "N/A"}
              </Text>
            </View>
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Source
              </Text>
              <Text className="mt-1 text-[11px] font-normal text-slate-300">
                {sessionSource ?? "N/A"}
              </Text>
            </View>
          </View>

          <View className="h-[1px] bg-white/5" />

          <View className="flex-row flex-wrap gap-4">
            {session?.runtimeStatus ? (
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                  Runtime
                </Text>
                <Text className="mt-1 text-[11px] font-normal text-slate-300">
                  {session.runtimeStatus}
                </Text>
              </View>
            ) : null}
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Transport
              </Text>
              <Text className="mt-1 text-[11px] font-normal text-slate-300">
                {session?.transport ?? "N/A"}
              </Text>
            </View>
          </View>

          <View className="h-[1px] bg-white/5" />

          {workingDirectory ? (
            <>
              <View>
                <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                  Working Directory
                </Text>
                <Text className="mt-1 break-all text-[11px] font-normal text-slate-300">
                  {workingDirectory}
                </Text>
              </View>
              <View className="h-[1px] bg-white/5" />
            </>
          ) : null}

          <View className="flex-row items-center justify-between">
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Diagnostics
            </Text>
            <Button
              label="Test"
              size="xs"
              variant="secondary"
              iconLeft="pulse-outline"
              loading={testingConnection}
              onPress={onTestConnection}
            />
          </View>

          <View className="h-[1px] bg-white/5" />

          <View>
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Capabilities
            </Text>
            <View className="mt-2 flex-row flex-wrap gap-2">
              {(session?.inputModes ?? ["text"]).map((mode) => (
                <View key={mode} className="rounded bg-slate-800 px-2.5 py-1">
                  <Text className="text-[9px] font-medium text-slate-400">
                    IN: {mode}
                  </Text>
                </View>
              ))}
              {(session?.outputModes ?? ["text"]).map((mode) => (
                <View key={mode} className="rounded bg-primary/10 px-2.5 py-1">
                  <Text className="text-[9px] font-medium text-primary/80">
                    OUT: {mode}
                  </Text>
                </View>
              ))}
            </View>
          </View>

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
