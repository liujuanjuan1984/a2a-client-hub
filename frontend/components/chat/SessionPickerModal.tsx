import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { FlatList, Modal, Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { type AgentSession } from "@/lib/chat-utils";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";

function SessionItem({
  conversationId,
  session,
  isActive,
  onSelect,
}: {
  conversationId: string;
  session: AgentSession;
  isActive: boolean;
  onSelect: (id: string) => void;
}) {
  const messages = useMessageStore((state) => state.messages[conversationId]);
  const firstUserMessage = messages?.find((m) => m.role === "user");
  const title = firstUserMessage?.content?.trim() || "New Session";
  const date = new Date(session.lastActiveAt).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Pressable
      className={`mb-2 flex-row items-center justify-between rounded-xl border p-3 ${
        isActive
          ? "border-primary bg-primary/10"
          : "border-slate-800 bg-slate-900"
      }`}
      onPress={() => onSelect(conversationId)}
    >
      <Text className="flex-1 text-sm text-slate-300" numberOfLines={2}>
        {title}
      </Text>
      <Text className="ml-2 text-[10px] text-slate-400">{date}</Text>
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
        <View className="w-full max-h-[80%] min-h-[50%] rounded-t-3xl border-t border-slate-800 bg-slate-950 p-6 sm:w-[480px] sm:rounded-3xl sm:border">
          <View className="mb-6 flex-row items-center justify-between">
            <Text className="text-lg font-semibold text-white">
              Chat History
            </Text>
            <Pressable
              onPress={onClose}
              className="rounded-full bg-slate-800 p-2"
              accessibilityRole="button"
              accessibilityLabel="Close session picker"
            >
              <Ionicons name="close" size={20} color="#cbd5e1" />
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
