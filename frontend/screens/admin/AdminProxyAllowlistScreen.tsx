import Ionicons from "@expo/vector-icons/Ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  Switch,
  Text,
  View,
} from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  createProxyAllowlistEntry,
  deleteProxyAllowlistEntry,
  listProxyAllowlist,
  updateProxyAllowlistEntry,
} from "@/lib/api/adminProxyAllowlist";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";

export function AdminProxyAllowlistScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();

  const [newHost, setNewHost] = useState("");
  const [newRemark, setNewRemark] = useState("");

  const { data, isLoading, isRefetching, refetch } = useQuery({
    queryKey: queryKeys.admin.proxyAllowlist(),
    queryFn: listProxyAllowlist,
    enabled: isReady && isAdmin,
  });

  const createMutation = useMutation({
    mutationFn: createProxyAllowlistEntry,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.proxyAllowlist(),
      });
      setNewHost("");
      setNewRemark("");
      toast.success("Allowlist entry added");
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to add entry");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateProxyAllowlistEntry(id, { is_enabled: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.proxyAllowlist(),
      });
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to update entry");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteProxyAllowlistEntry,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.proxyAllowlist(),
      });
      toast.success("Entry deleted");
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to delete entry");
    },
  });

  const handleAdd = () => {
    if (!newHost.trim()) {
      toast.error("Host pattern is required");
      return;
    }
    createMutation.mutate({
      host_pattern: newHost.trim(),
      remark: newRemark.trim() || undefined,
      is_enabled: true,
    });
  };

  const handleDelete = (id: string, host: string) => {
    Alert.alert("Delete Entry", `Are you sure you want to delete "${host}"?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: () => deleteMutation.mutate(id),
      },
    ]);
  };

  if (!isReady || (isLoading && !isRefetching)) {
    return <FullscreenLoader message="Loading allowlist..." />;
  }
  if (!isAdmin) {
    return null;
  }

  const items = data || [];

  return (
    <ScreenContainer>
      <PageHeader
        title="Proxy Allowlist"
        subtitle="Manage domains allowed for A2A proxying."
        rightElement={
          <IconButton
            accessibilityLabel="Go back"
            icon="chevron-back"
            size="sm"
            variant="secondary"
            onPress={() => {
              blurActiveElement();
              if (router.canGoBack()) {
                router.back();
              } else {
                router.replace("/admin");
              }
            }}
          />
        }
      />

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={
          <RefreshControl
            refreshing={isRefetching}
            onRefresh={refetch}
            tintColor="#fff"
          />
        }
      >
        {/* Add Entry Form */}
        <View className="bg-slate-900/50 rounded-xl p-4 mb-6 border border-slate-800">
          <Text className="text-slate-200 font-bold mb-3">
            Add New Host Pattern
          </Text>
          <Input
            placeholder="e.g. *.openai.com"
            value={newHost}
            onChangeText={setNewHost}
            className="mb-3"
          />
          <Input
            placeholder="Remark (optional)"
            value={newRemark}
            onChangeText={setNewRemark}
            className="mb-4"
          />
          <Button
            label="Add to Allowlist"
            onPress={handleAdd}
            loading={createMutation.isPending}
            variant="primary"
          />
        </View>

        {/* List Entries */}
        <Text className="text-slate-400 text-xs font-bold uppercase tracking-widest mb-3 px-1">
          Active Allowlist ({items.length})
        </Text>

        {items.length === 0 ? (
          <View className="py-10 items-center justify-center bg-slate-900/30 rounded-xl border border-dashed border-slate-800">
            <Ionicons name="shield-outline" size={32} color="#475569" />
            <Text className="text-slate-500 mt-2">
              No entries in allowlist yet.
            </Text>
          </View>
        ) : (
          items.map((item) => (
            <View
              key={item.id}
              className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 mb-3 flex-row items-center justify-between"
            >
              <View className="flex-1 mr-4">
                <Text className="text-slate-100 font-semibold text-base">
                  {item.host_pattern}
                </Text>
                {item.remark ? (
                  <Text className="text-slate-400 text-xs mt-1">
                    {item.remark}
                  </Text>
                ) : null}
              </View>

              <View className="flex-row items-center gap-3">
                <Switch
                  value={item.is_enabled}
                  onValueChange={(enabled) =>
                    updateMutation.mutate({ id: item.id, enabled })
                  }
                  trackColor={{ false: "#1e293b", true: "#0ea5e9" }}
                  thumbColor="#fff"
                />
                <Pressable
                  onPress={() => handleDelete(item.id, item.host_pattern)}
                  className="p-2"
                >
                  <Ionicons name="trash-outline" size={20} color="#ef4444" />
                </Pressable>
              </View>
            </View>
          ))
        )}

        <View className="mt-6 p-4 bg-blue-900/20 rounded-lg border border-blue-900/30">
          <View className="flex-row gap-2 items-center mb-1">
            <Ionicons name="information-circle" size={16} color="#7dd3fc" />
            <Text className="text-blue-300 font-bold text-xs uppercase">
              Note
            </Text>
          </View>
          <Text className="text-blue-200/70 text-xs leading-5">
            Entries added here will be merged with the static
            `a2a_proxy_allowed_hosts` defined in environment variables. Changes
            take effect immediately without service restart.
          </Text>
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}
