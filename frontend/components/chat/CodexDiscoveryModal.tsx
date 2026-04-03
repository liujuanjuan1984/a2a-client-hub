import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  useCodexDiscoveryListQuery,
  useCodexPluginReadQuery,
} from "@/hooks/useCodexDiscoveryQuery";
import {
  A2AExtensionCallError,
  type CodexDiscoveryCapability,
  type CodexDiscoveryItem,
  type CodexDiscoveryListKind,
  type CodexDiscoveryPlugin,
  type CodexDiscoveryStatus,
} from "@/lib/api/a2aExtensions";
import { type AgentSource } from "@/store/agents";

const resolveStatusMessage = (status: CodexDiscoveryStatus) => {
  if (status === "supported" || status === "partially_consumed") {
    return null;
  }
  if (status === "declared_not_consumed") {
    return "This agent declares Codex discovery, but Hub does not currently expose a consumable frontend entry for it.";
  }
  if (status === "unsupported") {
    return "This agent does not declare Codex discovery.";
  }
  return "Capability status is unavailable.";
};

const resolveQueryError = (error: unknown, fallback: string) => {
  if (error instanceof A2AExtensionCallError) {
    if (
      error.errorCode === "not_supported" ||
      error.errorCode === "method_not_supported"
    ) {
      return "This Codex discovery surface is not available for the current agent.";
    }
    if (error.errorCode === "upstream_payload_error") {
      return "The upstream returned a payload shape that Hub cannot safely display.";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
};

const resolvePluginContentPreview = (plugin: CodexDiscoveryPlugin | null) => {
  if (!plugin) {
    return null;
  }
  if (typeof plugin.content === "string" && plugin.content.trim()) {
    return plugin.content.trim();
  }
  if (
    plugin.content &&
    typeof plugin.content === "object" &&
    !Array.isArray(plugin.content)
  ) {
    const readme = (plugin.content as Record<string, unknown>).readme;
    if (typeof readme === "string" && readme.trim()) {
      return readme.trim();
    }
  }
  return null;
};

const renderMetadataValue = (value: unknown) => {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return "Structured value";
};

const DiscoveryRow = React.memo(function DiscoveryRow({
  item,
  active,
  onPress,
}: {
  item: CodexDiscoveryItem;
  active: boolean;
  onPress?: (() => void) | null;
}) {
  return (
    <Pressable
      className={`mb-2 rounded-2xl border p-4 ${
        active ? "border-primary bg-primary/10" : "border-white/10 bg-black/20"
      } ${onPress ? "" : "opacity-80"}`}
      onPress={onPress ?? undefined}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={
        onPress ? `Open ${item.title ?? item.name ?? item.id}` : undefined
      }
    >
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1">
          <Text
            className={
              active ? "font-medium text-primary" : "font-medium text-white"
            }
          >
            {item.title?.trim() || item.name?.trim() || item.id}
          </Text>
          <Text className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">
            {item.kind} · {item.id}
          </Text>
          {item.summary ? (
            <Text className="mt-2 text-sm text-slate-300">{item.summary}</Text>
          ) : null}
          {item.description ? (
            <Text className="mt-2 text-xs text-slate-400">
              {item.description}
            </Text>
          ) : null}
        </View>
        {onPress ? (
          <Ionicons
            name={active ? "document-text" : "document-text-outline"}
            size={18}
            color={active ? "#facc15" : "#94a3b8"}
          />
        ) : null}
      </View>

      {item.tags.length > 0 ? (
        <View className="mt-3 flex-row flex-wrap gap-2">
          {item.tags.map((tag) => (
            <View
              key={`${item.id}:${tag}`}
              className="rounded-full bg-slate-800 px-2.5 py-1"
            >
              <Text className="text-[10px] text-slate-300">{tag}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </Pressable>
  );
});
DiscoveryRow.displayName = "DiscoveryRow";

export function CodexDiscoveryModal({
  visible,
  onClose,
  agentId,
  source,
  codexDiscoveryStatus,
  codexDiscovery,
  availableTabs,
  canReadPlugins,
}: {
  visible: boolean;
  onClose: () => void;
  agentId?: string | null;
  source: AgentSource;
  codexDiscoveryStatus: CodexDiscoveryStatus;
  codexDiscovery: CodexDiscoveryCapability | null;
  availableTabs: CodexDiscoveryListKind[];
  canReadPlugins: boolean;
}) {
  const [activeTab, setActiveTab] = useState<CodexDiscoveryListKind | null>(
    null,
  );
  const [selectedPluginId, setSelectedPluginId] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) {
      setSelectedPluginId(null);
      return;
    }
    if (!activeTab || !availableTabs.includes(activeTab)) {
      setActiveTab(availableTabs[0] ?? null);
    }
  }, [activeTab, availableTabs, visible]);

  const skillsQuery = useCodexDiscoveryListQuery({
    agentId,
    source,
    kind: "skills",
    enabled: visible && activeTab === "skills",
  });
  const appsQuery = useCodexDiscoveryListQuery({
    agentId,
    source,
    kind: "apps",
    enabled: visible && activeTab === "apps",
  });
  const pluginsQuery = useCodexDiscoveryListQuery({
    agentId,
    source,
    kind: "plugins",
    enabled: visible && activeTab === "plugins",
  });
  const pluginQuery = useCodexPluginReadQuery({
    agentId,
    source,
    pluginId: selectedPluginId,
    enabled: visible && activeTab === "plugins" && canReadPlugins,
  });

  const activeListQuery =
    activeTab === "skills"
      ? skillsQuery
      : activeTab === "apps"
        ? appsQuery
        : pluginsQuery;
  const activeItems = activeListQuery.data?.items ?? [];
  const selectedPlugin =
    (pluginQuery.data?.plugin as CodexDiscoveryPlugin | null | undefined) ??
    null;
  const pluginPreview = resolvePluginContentPreview(selectedPlugin);
  const statusMessage = resolveStatusMessage(codexDiscoveryStatus);
  const methodSummary = useMemo(() => {
    if (!codexDiscovery) {
      return null;
    }
    const methodLabels: Record<string, string> = {
      skillsList: "skills",
      appsList: "apps",
      pluginsList: "plugins",
      pluginsRead: "plugin details",
      watch: "watch",
    };
    const enabled = Object.entries(codexDiscovery.methods)
      .filter(([, method]) => Boolean(method?.declared && method.consumedByHub))
      .map(([key]) => methodLabels[key] ?? key);
    return enabled.length > 0 ? enabled.join(", ") : null;
  }, [codexDiscovery]);

  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
    >
      <View className="flex-1 justify-end bg-black/60 sm:items-center sm:justify-center">
        <Pressable
          className="absolute inset-0"
          accessibilityRole="button"
          accessibilityLabel="Close Codex discovery"
          onPress={onClose}
        />
        <View className="w-full max-h-[84%] rounded-t-3xl border-t border-white/5 bg-surface p-6 sm:w-[min(94vw,860px)] sm:rounded-3xl sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <View className="flex-1 pr-4">
              <Text className="text-lg font-bold text-white">
                Codex Discovery
              </Text>
              <Text className="mt-1 text-xs text-slate-400">
                Browse normalized Codex skills, apps, and plugins through Hub
                APIs.
              </Text>
              {methodSummary ? (
                <Text className="mt-2 text-[11px] uppercase tracking-wider text-slate-500">
                  Enabled: {methodSummary}
                </Text>
              ) : null}
            </View>
            <Pressable
              onPress={onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close Codex discovery"
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>

          {statusMessage ? (
            <View className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-5">
              <Text className="text-amber-100">{statusMessage}</Text>
            </View>
          ) : (
            <>
              <View className="mb-4 flex-row flex-wrap gap-2">
                {availableTabs.map((tab) => {
                  const label =
                    tab === "skills"
                      ? "Skills"
                      : tab === "apps"
                        ? "Apps"
                        : "Plugins";
                  const active = tab === activeTab;
                  return (
                    <Button
                      key={tab}
                      label={label}
                      size="xs"
                      variant={active ? "primary" : "secondary"}
                      onPress={() => {
                        setActiveTab(tab);
                        if (tab !== "plugins") {
                          setSelectedPluginId(null);
                        }
                      }}
                    />
                  );
                })}
              </View>

              <ScrollView
                className="rounded-2xl border border-white/5 bg-black/20"
                contentContainerStyle={{ padding: 16 }}
              >
                {activeListQuery.isLoading ? (
                  <Text className="text-slate-400">
                    Loading {activeTab ?? "items"}...
                  </Text>
                ) : activeListQuery.isError ? (
                  <View className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-5">
                    <Text className="text-amber-100">
                      {resolveQueryError(
                        activeListQuery.error,
                        "Codex discovery request failed.",
                      )}
                    </Text>
                  </View>
                ) : activeItems.length === 0 ? (
                  <View className="rounded-2xl bg-black/20 px-4 py-5">
                    <Text className="text-slate-400">
                      No {activeTab ?? "discovery"} items available.
                    </Text>
                  </View>
                ) : (
                  activeItems.map((item) => (
                    <DiscoveryRow
                      key={`${item.kind}:${item.id}`}
                      item={item}
                      active={item.id === selectedPluginId}
                      onPress={
                        activeTab === "plugins" && canReadPlugins
                          ? () => setSelectedPluginId(item.id)
                          : null
                      }
                    />
                  ))
                )}

                {activeTab === "plugins" ? (
                  <View className="mt-4 rounded-2xl border border-white/10 bg-slate-900/70 p-4">
                    <View className="mb-3 flex-row items-center justify-between">
                      <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                        Plugin Details
                      </Text>
                      {!canReadPlugins ? (
                        <Text className="text-xs text-slate-500">
                          Plugin read is not exposed by this agent.
                        </Text>
                      ) : null}
                    </View>

                    {!canReadPlugins ? (
                      <Text className="text-sm text-slate-400">
                        Selectable plugin details are unavailable because the
                        upstream does not declare a consumable plugin read
                        method.
                      </Text>
                    ) : !selectedPluginId ? (
                      <Text className="text-sm text-slate-400">
                        Select a plugin to inspect normalized details.
                      </Text>
                    ) : pluginQuery.isLoading ? (
                      <Text className="text-sm text-slate-400">
                        Loading plugin details...
                      </Text>
                    ) : pluginQuery.isError ? (
                      <Text className="text-sm text-amber-100">
                        {resolveQueryError(
                          pluginQuery.error,
                          "Plugin details failed to load.",
                        )}
                      </Text>
                    ) : !selectedPlugin ? (
                      <Text className="text-sm text-slate-400">
                        No plugin details available.
                      </Text>
                    ) : (
                      <View>
                        <Text className="text-base font-medium text-white">
                          {selectedPlugin.title?.trim() ||
                            selectedPlugin.name?.trim() ||
                            selectedPlugin.id}
                        </Text>
                        <Text className="mt-1 text-[11px] uppercase tracking-wider text-slate-500">
                          plugin · {selectedPlugin.id}
                        </Text>
                        {selectedPlugin.summary ? (
                          <Text className="mt-3 text-sm text-slate-300">
                            {selectedPlugin.summary}
                          </Text>
                        ) : null}
                        {selectedPlugin.description ? (
                          <Text className="mt-2 text-sm text-slate-400">
                            {selectedPlugin.description}
                          </Text>
                        ) : null}
                        {selectedPlugin.tags.length > 0 ? (
                          <View className="mt-3 flex-row flex-wrap gap-2">
                            {selectedPlugin.tags.map((tag) => (
                              <View
                                key={`${selectedPlugin.id}:detail:${tag}`}
                                className="rounded-full bg-slate-800 px-2.5 py-1"
                              >
                                <Text className="text-[10px] text-slate-300">
                                  {tag}
                                </Text>
                              </View>
                            ))}
                          </View>
                        ) : null}
                        {pluginPreview ? (
                          <View className="mt-4 rounded-2xl bg-black/20 px-4 py-4">
                            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                              Guide
                            </Text>
                            <Text className="mt-2 text-sm leading-6 text-slate-300">
                              {pluginPreview}
                            </Text>
                          </View>
                        ) : (
                          <View className="mt-4 rounded-2xl bg-black/20 px-4 py-4">
                            <Text className="text-sm text-slate-400">
                              This plugin exposes structured detail content that
                              is not rendered as free-form text in the current
                              minimal UI.
                            </Text>
                          </View>
                        )}
                        {Object.keys(selectedPlugin.metadata).length > 0 ? (
                          <View className="mt-4 rounded-2xl bg-black/20 px-4 py-4">
                            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                              Metadata
                            </Text>
                            <View className="mt-3 gap-2">
                              {Object.entries(selectedPlugin.metadata).map(
                                ([key, value]) => (
                                  <View
                                    key={`${selectedPlugin.id}:meta:${key}`}
                                    className="flex-row items-start justify-between gap-3"
                                  >
                                    <Text className="flex-1 text-xs text-slate-500">
                                      {key}
                                    </Text>
                                    <Text className="flex-1 text-right text-xs text-slate-300">
                                      {renderMetadataValue(value)}
                                    </Text>
                                  </View>
                                ),
                              )}
                            </View>
                          </View>
                        ) : null}
                      </View>
                    )}
                  </View>
                ) : null}
              </ScrollView>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}
