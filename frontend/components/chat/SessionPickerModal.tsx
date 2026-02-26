import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { FlatList, Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { type AgentSession } from "@/lib/chat-utils";
import { useConversationTitleMap } from "@/lib/chatHistoryCache";
import { formatLocalDateTimeYmdHm } from "@/lib/datetime";
import { useChatStore } from "@/store/chat";

function SessionItem({
  conversationId,
  session,
  title,
  isActive,
  onSelect,
}: {
  conversationId: string;
  session: AgentSession;
  title: string;
  isActive: boolean;
  onSelect: (id: string) => void;
}) {
  const createdAtText = formatLocalDateTimeYmdHm(
    session.createdAt ?? session.lastActiveAt,
  );

  return (
    <Pressable
      className={`mb-2 flex-row items-center justify-between rounded-xl p-4 ${
        isActive ? "bg-primary/10 border border-primary/20" : "bg-black/20"
      }`}
      onPress={() => onSelect(conversationId)}
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
}

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
  const getSessionsByAgentId = useChatStore(
    (state) => state.getSessionsByAgentId,
  );
  const sessions = useChatStore((state) => state.sessions);

  const agentSessions = React.useMemo(() => {
    if (!agentId) return [];
    return getSessionsByAgentId(agentId);
  }, [agentId, getSessionsByAgentId, sessions]);
  const sessionTitles = useConversationTitleMap(
    agentSessions.map(([conversationId]) => conversationId),
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
            onPress={() => {
              onSelect(generateConversationId());
              onClose();
            }}
          />
          {agentSessions.length === 0 ? (
            <View className="py-8 items-center">
              <Text className="text-slate-400">No previous sessions.</Text>
            </View>
          ) : (
            <FlatList
              data={agentSessions}
              keyExtractor={(item) => item[0]}
              renderItem={({ item }) => (
                <SessionItem
                  conversationId={item[0]}
                  session={item[1]}
                  title={sessionTitles[item[0]] ?? "New Session"}
                  isActive={item[0] === currentConversationId}
                  onSelect={(id) => {
                    onSelect(id);
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
