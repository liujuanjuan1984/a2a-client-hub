import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentOpencodeSessionsQuery } from "@/hooks/useAgentOpencodeSessionsQuery";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useContinueOpencodeSession } from "@/hooks/useContinueOpencodeSession";
import { validateAgentCard } from "@/lib/api/a2aAgents";
import { validateHubAgentCard } from "@/lib/api/hubA2aAgentsUser";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import {
  getOpencodeSessionId,
  getOpencodeSessionTimestamp,
  getOpencodeSessionTitle,
} from "@/lib/opencodeAdapters";
import { supportsOpencodeSessionQuery } from "@/lib/opencodeSupport";

type SupportState = "checking" | "supported" | "unsupported" | "unknown";

export function OpencodeSessionsScreen({ agentId }: { agentId: string }) {
  const router = useRouter();
  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const agent = useMemo(
    () => agents.find((item) => item.id === agentId),
    [agents, agentId],
  );

  const [supportState, setSupportState] = useState<SupportState>("checking");
  const [supportMessage, setSupportMessage] = useState<string | null>(null);
  const [continuingSessionId, setContinuingSessionId] = useState<string | null>(
    null,
  );
  const source = agent?.source ?? "personal";
  const { continueSession: continueWithBinding } = useContinueOpencodeSession();

  const checkSupport = useCallback(async () => {
    setSupportState("checking");
    setSupportMessage(null);
    try {
      const response =
        source === "shared"
          ? await validateHubAgentCard(agentId)
          : await validateAgentCard(agentId);
      if (!response.success) {
        const raw = response.validation_errors?.[0] || response.message;
        const message =
          typeof raw === "string" && raw.trim()
            ? raw
            : "Could not validate agent card.";
        setSupportState("unknown");
        setSupportMessage(message);
        return;
      }
      const supported = supportsOpencodeSessionQuery(response.card);
      setSupportState(supported ? "supported" : "unsupported");
      setSupportMessage(
        supported
          ? null
          : "This agent does not advertise the OpenCode session query extension.",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Check failed.";
      setSupportState("unknown");
      setSupportMessage(message);
    }
  }, [agentId, source]);

  useEffect(() => {
    checkSupport().catch(() => {
      // Error already handled
    });
  }, [checkSupport]);

  const {
    items,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    reset,
    loadMore,
    loadFirstPage,
  } = useAgentOpencodeSessionsQuery({
    agentId,
    source,
    enabled: supportState === "supported",
  });

  useEffect(() => {
    if (supportState === "supported") return;
    reset();
  }, [reset, supportState]);

  const onRefresh = async () => {
    if (supportState !== "supported") return;
    await loadFirstPage("refreshing");
  };

  const continueSession = async (item: unknown) => {
    const opencodeSessionId = getOpencodeSessionId(item) ?? "";
    if (!opencodeSessionId) {
      await continueWithBinding({ agentId, sessionId: "", source });
      return;
    }
    setContinuingSessionId(opencodeSessionId);
    try {
      await continueWithBinding({
        agentId,
        sessionId: opencodeSessionId,
        source,
      });
    } finally {
      setContinuingSessionId(null);
    }
  };

  const subtitle = agent?.name ? `Agent: ${agent.name}` : `Agent: ${agentId}`;

  return (
    <ScreenContainer>
      <PageHeader
        title="OpenCode Sessions"
        subtitle={subtitle}
        rightElement={
          <Button
            label="Back"
            size="xs"
            variant="secondary"
            iconLeft="chevron-back"
            onPress={() => {
              blurActiveElement();
              if (router.canGoBack()) {
                router.back();
              } else {
                router.replace("/");
              }
            }}
          />
        }
      />

      {supportState === "checking" ? (
        <View className="mt-4 flex-row items-center gap-2">
          <Ionicons name="pulse-outline" size={16} color="#94a3b8" />
          <Text className="text-sm text-muted">
            Checking extension support...
          </Text>
        </View>
      ) : supportState === "unsupported" ? (
        <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
          <Text className="text-base font-semibold text-white">
            Extension not supported
          </Text>
          <Text className="mt-2 text-sm text-muted">
            {supportMessage ??
              "This agent does not support the OpenCode session query extension."}
          </Text>
          <Button
            className="mt-5 self-start"
            label="Re-check"
            size="sm"
            variant="secondary"
            onPress={() => checkSupport()}
          />
        </View>
      ) : supportMessage ? (
        <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-4">
          <Text className="text-sm text-muted">{supportMessage}</Text>
          <Button
            className="mt-3 self-start"
            label="Re-check"
            size="xs"
            variant="secondary"
            onPress={() => checkSupport()}
          />
        </View>
      ) : null}

      <ScrollView
        className="mt-2"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-muted">Loading sessions...</Text>
          </View>
        ) : items.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No sessions
            </Text>
            <Text className="mt-2 text-sm text-muted">
              No sessions found for this agent.
            </Text>
          </View>
        ) : (
          <>
            {items.map((item) => {
              const title = getOpencodeSessionTitle(item);
              const sessionId = getOpencodeSessionId(item);
              const ts = getOpencodeSessionTimestamp(item);
              return (
                <View
                  key={sessionId}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <Text
                      className="text-sm font-semibold text-white"
                      numberOfLines={1}
                    >
                      {title}
                    </Text>
                    <Text
                      className="mt-1 text-xs text-slate-400"
                      numberOfLines={1}
                    >
                      {sessionId}
                    </Text>
                    {ts ? (
                      <Text className="mt-2 text-xs text-slate-400">
                        Updated: {formatLocalDateTime(ts)}
                      </Text>
                    ) : null}
                  </View>

                  <View className="flex-row items-center justify-end gap-1 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <Pressable
                      className="flex-row items-center gap-2 rounded-lg px-3 py-2 active:bg-slate-800/40"
                      onPress={() => continueSession(item)}
                      accessibilityRole="button"
                      accessibilityLabel="Continue session in chat"
                      disabled={continuingSessionId === sessionId}
                    >
                      <Text className="text-xs font-semibold text-slate-200">
                        {continuingSessionId === sessionId
                          ? "Continuing..."
                          : "Continue"}
                      </Text>
                    </Pressable>
                  </View>
                </View>
              );
            })}

            {hasMore ? (
              <Button
                className="mt-2 self-center"
                label={loadingMore ? "Loading..." : "Load more"}
                size="sm"
                variant="secondary"
                loading={loadingMore}
                onPress={() => loadMore()}
              />
            ) : null}
          </>
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
