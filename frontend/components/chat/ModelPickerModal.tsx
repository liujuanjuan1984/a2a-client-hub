import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { FlatList, Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  A2AExtensionCallError,
  listOpencodeModels,
  listOpencodeProviders,
  type OpencodeModelSummary,
  type OpencodeProviderSummary,
} from "@/lib/api/a2aExtensions";
import { type SharedModelSelection } from "@/lib/chat-utils";
import { type AgentSource } from "@/store/agents";

const resolveDiscoveryError = (error: unknown) => {
  if (error instanceof A2AExtensionCallError) {
    if (error.errorCode === "not_supported") {
      return "This agent does not expose OpenCode model discovery.";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Model discovery failed.";
};

const extractDiscoveryMetadata = (
  metadata: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined => {
  const opencode =
    metadata && typeof metadata.opencode === "object" && metadata.opencode
      ? metadata.opencode
      : null;
  if (!opencode || Array.isArray(opencode)) {
    return undefined;
  }
  return { opencode: { ...(opencode as Record<string, unknown>) } };
};

function ProviderChip({
  item,
  active,
  onPress,
}: {
  item: OpencodeProviderSummary;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      className={`mr-2 rounded-xl border px-3 py-2 ${
        active ? "border-primary bg-primary/10" : "border-white/10 bg-black/20"
      }`}
      onPress={onPress}
    >
      <Text className={active ? "text-primary font-medium" : "text-white"}>
        {item.name?.trim() || item.provider_id}
      </Text>
      <Text className="mt-1 text-[11px] text-slate-400">
        {item.default_model_id?.trim() || "No default model"}
      </Text>
    </Pressable>
  );
}

function ModelRow({
  item,
  active,
  onPress,
}: {
  item: OpencodeModelSummary;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      className={`mb-2 rounded-xl border p-4 ${
        active ? "border-primary bg-primary/10" : "border-white/10 bg-black/20"
      }`}
      onPress={onPress}
    >
      <Text
        className={
          active ? "font-medium text-primary" : "font-medium text-white"
        }
      >
        {item.name?.trim() || item.model_id}
      </Text>
      <Text className="mt-1 text-[11px] text-slate-400">{item.model_id}</Text>
    </Pressable>
  );
}

export function ModelPickerModal({
  visible,
  onClose,
  agentId,
  source,
  sessionMetadata,
  selectedModel,
  onSelectModel,
  onClearModelSelection,
}: {
  visible: boolean;
  onClose: () => void;
  agentId?: string | null;
  source: AgentSource;
  sessionMetadata?: Record<string, unknown>;
  selectedModel: SharedModelSelection | null;
  onSelectModel: (selection: SharedModelSelection) => void;
  onClearModelSelection: () => void;
}) {
  const [providers, setProviders] = useState<OpencodeProviderSummary[]>([]);
  const [models, setModels] = useState<OpencodeModelSummary[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [providerError, setProviderError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    null,
  );
  const discoveryMetadata = extractDiscoveryMetadata(sessionMetadata);

  useEffect(() => {
    if (!visible || !agentId) {
      return;
    }
    let cancelled = false;
    setLoadingProviders(true);
    setProviderError(null);
    listOpencodeProviders({
      source,
      agentId,
      metadata: discoveryMetadata,
    })
      .then((result) => {
        if (cancelled) {
          return;
        }
        setProviders(result.items);
        const currentProvider = selectedModel?.providerID?.trim();
        const defaultProvider =
          (currentProvider &&
            result.items.find((item) => item.provider_id === currentProvider)
              ?.provider_id) ||
          result.connected[0] ||
          result.items[0]?.provider_id ||
          null;
        setSelectedProviderId(defaultProvider);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setProviders([]);
        setSelectedProviderId(null);
        setProviderError(resolveDiscoveryError(error));
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingProviders(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, discoveryMetadata, selectedModel?.providerID, source, visible]);

  useEffect(() => {
    if (!visible || !agentId || !selectedProviderId) {
      setModels([]);
      return;
    }
    let cancelled = false;
    setLoadingModels(true);
    setModelError(null);
    listOpencodeModels({
      source,
      agentId,
      providerId: selectedProviderId,
      metadata: discoveryMetadata,
    })
      .then((result) => {
        if (cancelled) {
          return;
        }
        setModels(result.items);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setModels([]);
        setModelError(resolveDiscoveryError(error));
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingModels(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, discoveryMetadata, selectedProviderId, source, visible]);

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
          accessibilityLabel="Close model picker"
          onPress={onClose}
        />
        <View className="w-full max-h-[80%] min-h-[52%] rounded-t-3xl border-t border-white/5 bg-surface p-6 sm:w-[min(94vw,760px)] sm:rounded-3xl sm:border lg:w-[min(90vw,960px)]">
          <View className="mb-6 flex-row items-center justify-between">
            <View>
              <Text className="text-lg font-bold text-white">Select Model</Text>
              <Text className="mt-1 text-xs text-slate-400">
                Selection is written to metadata.shared.model.
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close model picker"
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>

          <View className="mb-4 flex-row items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
            <View className="flex-1 pr-3">
              <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Current
              </Text>
              <Text className="mt-1 text-sm text-white" numberOfLines={1}>
                {selectedModel
                  ? `${selectedModel.providerID} / ${selectedModel.modelID}`
                  : "Server default"}
              </Text>
            </View>
            <Button
              label="Use Default"
              size="xs"
              variant="secondary"
              onPress={() => {
                onClearModelSelection();
                onClose();
              }}
            />
          </View>

          <Text className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-500">
            Providers
          </Text>
          {loadingProviders ? (
            <View className="rounded-2xl bg-black/20 px-4 py-5">
              <Text className="text-slate-400">Loading providers...</Text>
            </View>
          ) : providerError ? (
            <View className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-5">
              <Text className="text-amber-100">{providerError}</Text>
            </View>
          ) : (
            <FlatList
              horizontal
              data={providers}
              keyExtractor={(item) => item.provider_id}
              renderItem={({ item }) => (
                <ProviderChip
                  item={item}
                  active={item.provider_id === selectedProviderId}
                  onPress={() => setSelectedProviderId(item.provider_id)}
                />
              )}
              contentContainerStyle={{ paddingRight: 8, paddingBottom: 8 }}
              showsHorizontalScrollIndicator={false}
            />
          )}

          <View className="mb-2 mt-4 flex-row items-center justify-between">
            <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Models
            </Text>
            <Button
              label="Close"
              size="xs"
              variant="secondary"
              onPress={onClose}
            />
          </View>
          {loadingModels ? (
            <View className="rounded-2xl bg-black/20 px-4 py-5">
              <Text className="text-slate-400">Loading models...</Text>
            </View>
          ) : modelError ? (
            <View className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-5">
              <Text className="text-amber-100">{modelError}</Text>
            </View>
          ) : models.length === 0 ? (
            <View className="rounded-2xl bg-black/20 px-4 py-5">
              <Text className="text-slate-400">No models available.</Text>
            </View>
          ) : (
            <FlatList
              data={models}
              keyExtractor={(item) => `${item.provider_id}:${item.model_id}`}
              renderItem={({ item }) => (
                <ModelRow
                  item={item}
                  active={
                    selectedModel?.providerID === item.provider_id &&
                    selectedModel?.modelID === item.model_id
                  }
                  onPress={() => {
                    onSelectModel({
                      providerID: item.provider_id,
                      modelID: item.model_id,
                    });
                    onClose();
                  }}
                />
              )}
              contentContainerStyle={{ paddingBottom: 24 }}
            />
          )}
        </View>
      </View>
    </Modal>
  );
}
