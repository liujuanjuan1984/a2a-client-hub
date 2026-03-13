import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  createInvitation,
  listMyInvitations,
  restoreInvitation,
  revokeInvitation,
  type InvitationResponse,
} from "@/lib/api/invitations";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";

const statusColor = (status: InvitationResponse["status"]) => {
  if (status === "pending") return "text-amber-300";
  if (status === "registered") return "text-emerald-300";
  if (status === "revoked") return "text-red-300";
  return "text-slate-300";
};

export function AdminInvitationsScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();
  const hasShownLoadErrorRef = useRef(false);

  const [email, setEmail] = useState("");
  const [memo, setMemo] = useState("");

  const canCreate = useMemo(() => Boolean(email.trim()), [email]);

  const invitationsQuery = useQuery({
    queryKey: queryKeys.admin.invitations(),
    queryFn: () => listMyInvitations(1, 200),
    enabled: isReady && isAdmin,
  });

  useEffect(() => {
    if (!invitationsQuery.isError || !invitationsQuery.error) {
      hasShownLoadErrorRef.current = false;
      return;
    }
    if (hasShownLoadErrorRef.current) return;
    hasShownLoadErrorRef.current = true;
    const message =
      invitationsQuery.error instanceof Error
        ? invitationsQuery.error.message
        : "Could not load invitations.";
    toast.error("Load invitations failed", message);
  }, [invitationsQuery.error, invitationsQuery.isError]);

  const invalidateInvitations = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.invitations(),
    });
  }, [queryClient]);

  const createMutation = useMutation({
    mutationFn: async () => {
      return await createInvitation({
        email: email.trim(),
        memo: memo.trim() || null,
      });
    },
    onSuccess: async (created) => {
      setEmail("");
      setMemo("");
      toast.success("Invitation created", `${created.target_email}`);
      await invalidateInvitations();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Create failed.";
      toast.error("Create failed", message);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: async (invitationId: string) => {
      await revokeInvitation(invitationId);
    },
    onSuccess: async () => {
      toast.success("Invitation revoked", "The invitation has been revoked.");
      await invalidateInvitations();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Revoke failed.";
      toast.error("Revoke failed", message);
    },
  });

  const restoreMutation = useMutation({
    mutationFn: async (invitationId: string) => {
      await restoreInvitation(invitationId);
    },
    onSuccess: async () => {
      toast.success("Invitation restored", "The invitation has been restored.");
      await invalidateInvitations();
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Restore failed.";
      toast.error("Restore failed", message);
    },
  });

  const items = invitationsQuery.data?.items ?? [];

  const handleCreate = async () => {
    if (!canCreate || createMutation.isPending) return;
    blurActiveElement();
    await createMutation.mutateAsync();
  };

  const handleRevoke = async (invitationId: string) => {
    blurActiveElement();
    await revokeMutation.mutateAsync(invitationId);
  };

  const handleRestore = async (invitationId: string) => {
    blurActiveElement();
    await restoreMutation.mutateAsync(invitationId);
  };

  const buildInvitationLink = useCallback(
    (code: string, emailValue: string) => {
      // Align with the Compass web frontend params for familiarity.
      return Linking.createURL("/register", {
        queryParams: {
          invite: code,
          email: emailValue,
        },
      });
    },
    [],
  );

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }
  if (invitationsQuery.isLoading) {
    return <FullscreenLoader message="Loading invitations..." />;
  }

  return (
    <ScreenContainer>
      <PageHeader
        title="Invitations"
        subtitle="Create and manage invitation codes."
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
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={invitationsQuery.isRefetching}
            onRefresh={() => invitationsQuery.refetch()}
            tintColor="#5c6afb"
            colors={["#5c6afb"]}
          />
        }
      >
        <View className="rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Create invitation
          </Text>
          <View className="mt-4 gap-3">
            <Input
              label="Target email"
              placeholder="user@example.com"
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
            />
            <Input
              label="Memo (optional)"
              placeholder="Short note"
              value={memo}
              onChangeText={setMemo}
            />
            <Button
              label={createMutation.isPending ? "Creating..." : "Create"}
              loading={createMutation.isPending}
              onPress={handleCreate}
              disabled={!canCreate || createMutation.isPending}
            />
          </View>
        </View>

        <View className="mt-6 flex-row items-center justify-between">
          <Text className="text-base font-semibold text-white">
            My invitations
          </Text>
          <Text className="text-xs text-muted">{items.length} total</Text>
        </View>

        {invitationsQuery.isError ? (
          <View className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-6">
            <Text className="text-base font-semibold text-red-200">
              Load invitations failed
            </Text>
            <Text className="mt-2 text-sm text-red-100/90">
              {invitationsQuery.error instanceof Error
                ? invitationsQuery.error.message
                : "Could not load invitations."}
            </Text>
            <Button
              className="mt-4 self-start"
              label={invitationsQuery.isRefetching ? "Retrying..." : "Retry"}
              size="sm"
              variant="secondary"
              onPress={() => invitationsQuery.refetch()}
              loading={invitationsQuery.isRefetching}
            />
          </View>
        ) : items.length === 0 ? (
          <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No invitations
            </Text>
            <Text className="mt-2 text-sm text-muted">
              Create an invitation to onboard a new user.
            </Text>
          </View>
        ) : (
          items.map((inv) => (
            <View
              key={inv.id}
              className="mt-3 overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/30"
            >
              <View className="p-5">
                <View className="flex-row items-start justify-between">
                  <View className="flex-1 pr-4">
                    <Text className="text-base font-semibold text-white">
                      {inv.target_email}
                    </Text>
                    <View className="mt-2 flex-row items-center gap-2">
                      {inv.status === "pending" ? (
                        <CopyButton
                          value={buildInvitationLink(
                            inv.code,
                            inv.target_email,
                          )}
                          successMessage="Invitation link copied."
                          accessibilityLabel="Copy invitation link"
                          variant="ghost"
                          size="xs"
                          className="rounded-lg mr-1"
                        />
                      ) : null}
                      <Text
                        className="flex-1 font-mono text-[11px] text-muted"
                        numberOfLines={1}
                        selectable
                      >
                        {buildInvitationLink(inv.code, inv.target_email)}
                      </Text>
                    </View>
                    {inv.memo ? (
                      <Text className="mt-2 text-xs text-slate-300">
                        {inv.memo}
                      </Text>
                    ) : null}
                  </View>
                  <View className="items-end">
                    <Text
                      className={`text-xs font-bold ${statusColor(inv.status)}`}
                    >
                      {inv.status.toUpperCase()}
                    </Text>
                  </View>
                </View>
              </View>

              <View className="flex-row items-center justify-end gap-1 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                {inv.status === "pending" ? (
                  <Button
                    size="xs"
                    variant="secondary"
                    label="Revoke"
                    onPress={() => handleRevoke(inv.id)}
                    loading={revokeMutation.isPending}
                    disabled={revokeMutation.isPending}
                  />
                ) : inv.status === "revoked" ? (
                  <Button
                    size="xs"
                    variant="secondary"
                    label="Restore"
                    onPress={() => handleRestore(inv.id)}
                    loading={restoreMutation.isPending}
                    disabled={restoreMutation.isPending}
                  />
                ) : null}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
