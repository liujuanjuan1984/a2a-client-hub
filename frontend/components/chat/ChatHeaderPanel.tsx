import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { BackButton } from "@/components/ui/BackButton";
import { Button } from "@/components/ui/Button";
import { type AgentSession } from "@/lib/chat-utils";
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
  return (
    <View
      className="border-b border-slate-800 bg-background/80 px-6 pb-4"
      style={{ paddingTop: topInset }}
    >
      <View className="flex-row items-center justify-between">
        <View className="flex-1 flex-row items-center gap-2">
          <View>
            <Text className="text-lg font-bold text-white" numberOfLines={1}>
              {agent.name}
            </Text>
          </View>
        </View>
        <View className="flex-row items-center gap-3">
          <BackButton />
          <Pressable
            className="h-10 w-10 items-center justify-center rounded-full bg-primary"
            onPress={onOpenSessionPicker}
            accessibilityRole="button"
            accessibilityLabel="Show sessions"
            accessibilityHint="View and switch chat sessions"
          >
            <Ionicons name="list" size={20} color="#ffffff" />
          </Pressable>
          <Pressable
            className={`h-10 w-10 items-center justify-center rounded-full border border-slate-700 ${
              showDetails ? "bg-slate-700" : ""
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
              color="#ffffff"
            />
          </Pressable>
        </View>
      </View>

      {showDetails ? (
        <View className="mt-4 gap-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
          <View>
            <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
              Agent Endpoint
            </Text>
            <Text className="mt-1 break-all text-xs text-white">
              {agent.cardUrl}
            </Text>
          </View>

          <View className="h-[1px] bg-slate-800" />

          <View className="flex-row flex-wrap gap-4">
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Conversation ID
              </Text>
              <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                {conversationId ?? "N/A"}
              </Text>
            </View>
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Source
              </Text>
              <Text className="mt-1 text-xs text-white">
                {sessionSource ?? "N/A"}
              </Text>
            </View>
          </View>

          <View className="h-[1px] bg-slate-800" />

          <View className="flex-row flex-wrap gap-4">
            {session?.runtimeStatus ? (
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Runtime
                </Text>
                <Text className="mt-1 text-xs text-white">
                  {session.runtimeStatus}
                </Text>
              </View>
            ) : null}
            <View className="flex-1 min-w-[45%]">
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Transport
              </Text>
              <Text className="mt-1 text-xs text-white">
                {session?.transport ?? "N/A"}
              </Text>
            </View>
            {session?.contextId ? (
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Context ID
                </Text>
                <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                  {session.contextId}
                </Text>
              </View>
            ) : null}
            {session?.externalSessionRef?.provider ? (
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Provider
                </Text>
                <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                  {session.externalSessionRef.provider}
                </Text>
              </View>
            ) : null}
            {session?.externalSessionRef?.externalSessionId ? (
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  External Session
                </Text>
                <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                  {session.externalSessionRef.externalSessionId}
                </Text>
              </View>
            ) : null}
          </View>

          <View className="h-[1px] bg-slate-800" />

          <View className="flex-row items-center justify-between">
            <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
              Diagnostics
            </Text>
            <Button
              label="Test Connection"
              size="sm"
              variant="secondary"
              iconLeft="pulse-outline"
              loading={testingConnection}
              onPress={onTestConnection}
            />
          </View>

          <View className="h-[1px] bg-slate-800" />

          <View>
            <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
              Capabilities
            </Text>
            <View className="mt-2 flex-row flex-wrap gap-2">
              {(session?.inputModes ?? ["text"]).map((mode) => (
                <View key={mode} className="rounded bg-slate-800 px-2 py-1">
                  <Text className="text-[9px] text-white">IN: {mode}</Text>
                </View>
              ))}
              {(session?.outputModes ?? ["text"]).map((mode) => (
                <View key={mode} className="rounded bg-primary/20 px-2 py-1">
                  <Text className="text-[9px] text-primary">OUT: {mode}</Text>
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
