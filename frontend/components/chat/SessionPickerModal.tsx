import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useMemo } from "react";
import { FlatList, Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import { type SessionListItem } from "@/lib/api/sessions";
import { formatLocalDateTimeYmdHm } from "@/lib/datetime";
import { useChatStore } from "@/store/chat";

const LIST_CONTENT_CONTAINER_STYLE = { paddingBottom: 24 };

const SessionItem = React.memo(function SessionItem({
  item,
  isActive,
  onSelect,
}: {
  item: SessionListItem;
  isActive: boolean;
  onSelect: (id: string) => void;
}) {
  const createdAtText = formatLocalDateTimeYmdHm(
    item.created_at ?? item.last_active_at,
  );
  const title =
    typeof item.title === "string" && item.title.trim().length > 0
      ? item.title
      : "Session";

  return (
    <Pressable
      className={`mb-2 flex-row items-center justify-between rounded-xl p-4 ${
        isActive ? "bg-primary/10 border border-primary/20" : "bg-black/20"
      }`}
      onPress={() => onSelect(item.conversationId)}
    >
      <View className="flex-1">
        <Text
          className={`text-sm font-medium ${isActive ? "text-primary" : "text-white"}`}
          numberOfLines={2}
        >
          {title}
        </Text>
        <Text
          className="mt-1 text-[11px] font-medium text-slate-500"
          numberOfLines={1}
        >
          {createdAtText}
        </Text>
      </View>
    </Pressable>
  );
});

SessionItem.displayName = "SessionItem";

export function SessionPickerModal({
  visible,
  onClose,
  agentId,
  currentConversationId,
  onSelect,
}: {
  visible: boolean;
  onClose: () => void;
  agentId?: string | null;
  currentConversationId?: string | null;
  onSelect: (id: string) => void;
}) {
  const generateConversationId = useChatStore(
    (state) => state.generateConversationId,
  );
  const normalizedAgentId =
    typeof agentId === "string" && agentId.trim().length > 0
      ? agentId.trim()
      : null;
  const keyExtractor = useCallback(
    (item: SessionListItem) => item.conversationId,
    [],
  );

  const {
    items: agentSessions,
    loading,
    loadingMore,
    hasMore,
    loadMore,
  } = useSessionsDirectoryQuery({
    agentId: normalizedAgentId,
    enabled: visible && Boolean(normalizedAgentId),
    size: 50,
  });
  const handleSelectSession = useCallback(
    (id: string) => {
      onSelect(id);
      onClose();
    },
    [onClose, onSelect],
  );
  const handleCreateSession = useCallback(() => {
    handleSelectSession(generateConversationId());
  }, [generateConversationId, handleSelectSession]);
  const handleEndReached = useCallback(() => {
    if (!hasMore || loadingMore) return;
    loadMore().catch(() => undefined);
  }, [hasMore, loadMore, loadingMore]);
  const renderSessionItem = useCallback(
    ({ item }: { item: SessionListItem }) => (
      <SessionItem
        item={item}
        isActive={item.conversationId === currentConversationId}
        onSelect={handleSelectSession}
      />
    ),
    [currentConversationId, handleSelectSession],
  );
  const listFooterComponent = useMemo(
    () =>
      loadingMore ? (
        <View className="py-3 items-center">
          <Text className="text-[11px] text-slate-500">Loading…</Text>
        </View>
      ) : null,
    [loadingMore],
  );

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
          accessibilityLabel="Close session picker"
          onPress={onClose}
        />
        <View className="w-full max-h-[80%] min-h-[50%] rounded-t-3xl bg-surface p-6 sm:w-[min(94vw,760px)] lg:w-[min(90vw,960px)] sm:rounded-3xl border-t border-white/5 sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <Text className="text-lg font-bold text-white">Chat History</Text>
            <Pressable
              onPress={onClose}
              className="rounded-xl bg-slate-800 p-2 active:bg-slate-700"
              accessibilityRole="button"
              accessibilityLabel="Close session picker"
            >
              <Ionicons name="close" size={20} color="#FFFFFF" />
            </Pressable>
          </View>
          <Button
            className="mb-4"
            label="New Session"
            iconLeft="add"
            onPress={handleCreateSession}
          />
          {!normalizedAgentId ? (
            <View className="py-8 items-center">
              <Text className="text-slate-400">No agent selected.</Text>
            </View>
          ) : loading ? (
            <View className="py-8 items-center">
              <Text className="text-slate-400">Loading sessions...</Text>
            </View>
          ) : agentSessions.length === 0 ? (
            <View className="py-8 items-center">
              <Text className="text-slate-400">No previous sessions.</Text>
            </View>
          ) : (
            <FlatList
              data={agentSessions}
              keyExtractor={keyExtractor}
              renderItem={renderSessionItem}
              onEndReachedThreshold={0.4}
              onEndReached={handleEndReached}
              contentContainerStyle={LIST_CONTENT_CONTAINER_STYLE}
              ListFooterComponent={listFooterComponent}
            />
          )}
        </View>
      </View>
    </Modal>
  );
}
