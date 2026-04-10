import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { ScreenScrollView } from "@/components/layout/ScreenScrollView";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useChangePassword, useLogout } from "@/hooks/useAuth";
import { ApiRequestError, isAuthFailureError } from "@/lib/api/client";
import { getFriendlyAuthErrorMessage } from "@/lib/authErrorMessage";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
import { resetAuthBoundState } from "@/lib/resetClientState";
import { toast } from "@/lib/toast";
import { useSessionStore } from "@/store/session";

function AccountSummary() {
  const user = useSessionStore((state) => state.user);

  return (
    <View className="rounded-2xl border border-white/10 bg-surface px-4 py-4">
      <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        Account
      </Text>
      <Text className="mt-3 text-base font-semibold text-white">
        {user?.name || "Unknown user"}
      </Text>
      <Text className="mt-1 text-sm text-slate-400">
        {user?.email || "No email"}
      </Text>
    </View>
  );
}

export function AccountSecurityScreen() {
  const router = useRouter();
  const changePassword = useChangePassword();
  const logout = useLogout();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const closeScreen = useCallback(() => {
    backOrHome(router, "/");
  }, [router]);

  const finishSignedOutFlow = useCallback(() => {
    resetAuthBoundState();
    router.replace("/login");
  }, [router]);

  const canSubmitPassword = useMemo(() => {
    if (changePassword.isPending || logout.isPending) {
      return false;
    }
    return Boolean(
      currentPassword.trim() && newPassword.trim() && confirmPassword.trim(),
    );
  }, [
    changePassword.isPending,
    confirmPassword,
    currentPassword,
    logout.isPending,
    newPassword,
  ]);

  const changePasswordError = getFriendlyAuthErrorMessage(changePassword.error);

  const handleChangePassword = useCallback(async () => {
    if (!canSubmitPassword) {
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("Validation failed", "Password confirmation does not match.");
      return;
    }

    blurActiveElement();

    try {
      await changePassword.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirm: confirmPassword,
      });
      toast.success("Password updated", "Please sign in again.");
      finishSignedOutFlow();
    } catch {
      // Error is surfaced through mutation state.
    }
  }, [
    canSubmitPassword,
    changePassword,
    confirmPassword,
    currentPassword,
    finishSignedOutFlow,
    newPassword,
  ]);

  const handleLogout = useCallback(async () => {
    if (logout.isPending || changePassword.isPending) {
      return;
    }

    blurActiveElement();

    try {
      await logout.mutateAsync();
      toast.success("Signed out", "Session cleared.");
      finishSignedOutFlow();
    } catch (error) {
      if (isAuthFailureError(error)) {
        finishSignedOutFlow();
        return;
      }
      const message =
        error instanceof ApiRequestError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Unable to sign out.";
      toast.error("Sign out failed", message);
    }
  }, [changePassword.isPending, finishSignedOutFlow, logout]);

  return (
    <ScreenScrollView
      className="flex-1 bg-background px-5 sm:px-6"
      contentContainerStyle={{ paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled"
    >
      <PageHeader
        title="Account"
        subtitle="Security actions for the current session."
        rightElement={
          <IconButton
            accessibilityLabel="Close account security"
            icon="close"
            size="sm"
            variant="secondary"
            onPress={closeScreen}
          />
        }
      />

      <View className="mt-6 gap-4">
        <AccountSummary />

        <View className="rounded-2xl border border-white/10 bg-surface px-4 py-4">
          <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
            Change Password
          </Text>
          <View className="mt-4 gap-4">
            <Input
              label="Current password"
              placeholder="••••••••"
              secureTextEntry
              value={currentPassword}
              onChangeText={setCurrentPassword}
            />
            <Input
              label="New password"
              placeholder="••••••••"
              secureTextEntry
              value={newPassword}
              onChangeText={setNewPassword}
            />
            <Input
              label="Confirm new password"
              placeholder="••••••••"
              secureTextEntry
              value={confirmPassword}
              onChangeText={setConfirmPassword}
            />
          </View>
          <Text className="mt-3 text-xs text-slate-400">
            Password must be at least 8 characters and include upper, lower,
            number, and special characters.
          </Text>
          {changePasswordError ? (
            <Text className="mt-3 text-sm text-accent">
              {changePasswordError}
            </Text>
          ) : null}
          <Button
            className="mt-5"
            label={changePassword.isPending ? "Updating..." : "Change Password"}
            onPress={handleChangePassword}
            disabled={!canSubmitPassword}
            loading={changePassword.isPending}
          />
        </View>

        <View className="rounded-2xl border border-white/10 bg-surface px-4 py-4">
          <Text className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
            Session
          </Text>
          <Text className="mt-3 text-sm text-slate-400">
            End the current session on this device.
          </Text>
          <Button
            className="mt-5"
            label={logout.isPending ? "Signing out..." : "Logout"}
            variant="secondary"
            onPress={handleLogout}
            disabled={logout.isPending || changePassword.isPending}
            loading={logout.isPending}
          />
        </View>
      </View>
    </ScreenScrollView>
  );
}
