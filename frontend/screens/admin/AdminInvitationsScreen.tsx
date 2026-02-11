import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAsyncListLoad } from "@/hooks/useAsyncListLoad";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  createInvitation,
  listMyInvitations,
  restoreInvitation,
  revokeInvitation,
  type InvitationResponse,
} from "@/lib/api/invitations";
import { blurActiveElement } from "@/lib/focus";
import { toast } from "@/lib/toast";

const statusColor = (status: InvitationResponse["status"]) => {
  if (status === "pending") return "text-amber-300";
  if (status === "registered") return "text-emerald-300";
  if (status === "revoked") return "text-red-300";
  return "text-slate-300";
};

export function AdminInvitationsScreen() {
  const router = useRouter();
  const { isReady, isAdmin } = useRequireAdmin();
  const { loading, refreshing, run } = useAsyncListLoad();

  const [email, setEmail] = useState("");
  const [memo, setMemo] = useState("");
  const [items, setItems] = useState<InvitationResponse[]>([]);

  const canCreate = useMemo(() => Boolean(email.trim()), [email]);

  const load = useCallback(
    async (mode: "loading" | "refreshing" = "loading") => {
      await run(
        async () => {
          const response = await listMyInvitations(1, 200);
          setItems(response.items);
        },
        {
          mode,
          errorTitle: "Load invitations failed",
          fallbackMessage: "Could not load invitations.",
        },
      );
    },
    [run],
  );

  useEffect(() => {
    if (!isReady || !isAdmin) return;
    load().catch(() => {
      // Error already handled
    });
  }, [isReady, isAdmin, load]);

  const handleCreate = async () => {
    if (!canCreate) return;
    blurActiveElement();
    try {
      const created = await createInvitation({
        email: email.trim(),
        memo: memo.trim() || null,
      });
      setEmail("");
      setMemo("");
      toast.success("Invitation created", `${created.target_email}`);
      await load("refreshing");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Create failed.";
      toast.error("Create failed", message);
    }
  };

  const handleRevoke = async (invitationId: string) => {
    blurActiveElement();
    try {
      await revokeInvitation(invitationId);
      toast.success("Invitation revoked", "The invitation has been revoked.");
      await load("refreshing");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Revoke failed.";
      toast.error("Revoke failed", message);
    }
  };

  const handleRestore = async (invitationId: string) => {
    blurActiveElement();
    try {
      await restoreInvitation(invitationId);
      toast.success("Invitation restored", "The invitation has been restored.");
      await load("refreshing");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Restore failed.";
      toast.error("Restore failed", message);
    }
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

  const handleCopyLink = useCallback(async (link: string) => {
    try {
      await Clipboard.setStringAsync(link);
      toast.success("Copied", "Invitation link copied.");
    } catch {
      toast.error("Copy failed", "Could not copy invitation link.");
    }
  }, []);

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <View className="flex-1 bg-background px-6 pt-8">
      <PageHeader
        title="Invitations"
        subtitle="Create and manage invitation codes."
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
                router.replace("/admin");
              }
            }}
          />
        }
      />

      <ScrollView
        className="mt-3"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load("refreshing")}
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
              label={loading ? "Creating..." : "Create"}
              loading={loading}
              onPress={handleCreate}
              disabled={!canCreate || loading}
            />
          </View>
        </View>

        <View className="mt-6 flex-row items-center justify-between">
          <Text className="text-base font-semibold text-white">
            My invitations
          </Text>
          <Text className="text-xs text-muted">{items.length} total</Text>
        </View>

        {items.length === 0 ? (
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
                        <Pressable
                          className="flex-row items-center gap-1 rounded-lg px-2 py-2 active:bg-slate-800/40"
                          onPress={() =>
                            handleCopyLink(
                              buildInvitationLink(inv.code, inv.target_email),
                            )
                          }
                          accessibilityRole="button"
                          accessibilityLabel="Copy invitation link"
                        >
                          <Ionicons
                            name="copy-outline"
                            size={14}
                            color="#94a3b8"
                          />
                          <Text className="text-xs font-medium text-slate-300">
                            Copy
                          </Text>
                        </Pressable>
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

              <View className="flex-row items-center justify-end gap-2 border-t border-slate-800/50 bg-slate-900/50 px-5 py-3">
                {inv.status === "pending" ? (
                  <Pressable
                    className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                    onPress={() => handleRevoke(inv.id)}
                    accessibilityRole="button"
                    accessibilityLabel="Disable invitation"
                  >
                    <Ionicons name="trash-outline" size={14} color="#f87171" />
                    <Text className="text-xs font-medium text-red-300">
                      Disable
                    </Text>
                  </Pressable>
                ) : null}
                {inv.status === "revoked" ? (
                  <Pressable
                    className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                    onPress={() => handleRestore(inv.id)}
                    accessibilityRole="button"
                    accessibilityLabel="Enable invitation"
                  >
                    <Ionicons
                      name="refresh-outline"
                      size={14}
                      color="#94a3b8"
                    />
                    <Text className="text-xs font-medium text-slate-300">
                      Enable
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}
