import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { Input } from "@/components/ui/Input";
import { useRegister } from "@/hooks/useAuth";
import { ApiRequestError } from "@/lib/api/client";
import { lookupInvitation } from "@/lib/api/invitations";
import { blurActiveElement } from "@/lib/focus";
import { toast } from "@/lib/toast";

const detectTimezone = (): string | undefined => {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return typeof tz === "string" && tz.trim().length > 0 ? tz : undefined;
  } catch {
    return undefined;
  }
};

const toStringParam = (value: unknown): string | undefined => {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return undefined;
};

export function RegisterScreen() {
  const router = useRouter();
  const register = useRegister();
  const params = useLocalSearchParams();

  const inviteFromUrl = useMemo(() => {
    const raw =
      toStringParam(params.invite) ??
      toStringParam(params.invite_code) ??
      toStringParam(params.code);
    return raw?.trim() ? raw.trim() : undefined;
  }, [params.code, params.invite, params.invite_code]);

  const presetEmail = useMemo(() => {
    const raw = toStringParam(params.email);
    return raw?.trim() ? raw.trim() : undefined;
  }, [params.email]);

  const [inviteCode, setInviteCode] = useState(inviteFromUrl ?? "");
  const [email, setEmail] = useState(presetEmail ?? "");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  const inviteEnabled = Boolean(inviteCode.trim());
  const inviteLookupQuery = useQuery({
    queryKey: ["invitation-lookup", inviteCode.trim()],
    queryFn: () => lookupInvitation(inviteCode.trim()),
    enabled: inviteEnabled,
    retry: false,
  });

  const inviteEmail = inviteLookupQuery.data?.target_email ?? presetEmail;
  const emailLocked = inviteEnabled && Boolean(inviteLookupQuery.data);
  const inviteInvalid = inviteEnabled && inviteLookupQuery.isError;

  useEffect(() => {
    if (!inviteEmail) return;
    setEmail(inviteEmail);
  }, [inviteEmail]);

  const canSubmit = useMemo(() => {
    if (!email.trim() || !name.trim() || !password) return false;
    if (password.length < 8) return false;
    if (inviteInvalid) return false;
    if (inviteEnabled && inviteLookupQuery.isFetching) return false;
    return true;
  }, [
    email,
    inviteEnabled,
    inviteInvalid,
    inviteLookupQuery.isFetching,
    name,
    password,
  ]);

  const errorMessage =
    register.error instanceof ApiRequestError
      ? register.error.message
      : register.error instanceof Error
        ? register.error.message
        : null;

  const submit = async () => {
    if (!canSubmit || register.isPending) return;
    blurActiveElement();
    try {
      await register.mutateAsync({
        email: email.trim(),
        name: name.trim(),
        password,
        timezone: detectTimezone(),
        invite_code: inviteCode.trim() || undefined,
      });
      toast.success("Registered", "Welcome!");
      router.replace("/");
    } catch {
      // Error already exposed via mutation state/toast patterns.
    }
  };

  // While verifying URL-supplied invites, show a minimal loader to avoid flicker.
  const checkingInvite = Boolean(inviteFromUrl) && inviteLookupQuery.isFetching;
  if (checkingInvite) {
    return <FullscreenLoader message="Verifying invitation..." />;
  }

  return (
    <View className="flex-1 bg-background px-6 pt-20">
      <Text className="text-3xl font-semibold text-white">Create account</Text>
      <Text className="mt-2 text-base text-muted">
        Register with your invitation link.
      </Text>

      {inviteEnabled ? (
        <View className="mt-6 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
          {inviteLookupQuery.data ? (
            <>
              <Text className="text-sm font-semibold text-emerald-200">
                Invitation verified
              </Text>
              <Text className="mt-1 text-sm text-muted">
                Invitee: {inviteLookupQuery.data.target_email}
              </Text>
              {inviteLookupQuery.data.creator_name ? (
                <Text className="mt-1 text-xs text-muted">
                  Inviter: {inviteLookupQuery.data.creator_name}
                  {inviteLookupQuery.data.creator_email
                    ? ` (${inviteLookupQuery.data.creator_email})`
                    : ""}
                </Text>
              ) : null}
            </>
          ) : inviteInvalid ? (
            <Text className="text-sm text-accent">
              Invalid invitation code.
            </Text>
          ) : (
            <Text className="text-sm text-muted">
              Invitation code detected.
            </Text>
          )}
        </View>
      ) : null}

      <View className="mt-10 gap-4">
        <Input
          label="Invitation code"
          placeholder="(optional)"
          autoCapitalize="none"
          value={inviteCode}
          onChangeText={setInviteCode}
          editable={inviteFromUrl == null}
        />

        <Input
          label="Email"
          placeholder="you@example.com"
          autoCapitalize="none"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
          editable={!emailLocked}
        />

        <Input
          label="Name"
          placeholder="Your name"
          value={name}
          onChangeText={setName}
        />

        <Input
          label="Password"
          placeholder="••••••••"
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />
        <Text className="text-xs text-muted">
          Password must be at least 8 characters.
        </Text>
      </View>

      <Button
        className="mt-8"
        label={register.isPending ? "Registering..." : "Register"}
        onPress={submit}
        disabled={!canSubmit || register.isPending}
        loading={register.isPending}
      />

      {errorMessage ? (
        <Text className="mt-4 text-sm text-accent">{errorMessage}</Text>
      ) : null}

      <Pressable
        className="mt-6"
        onPress={() => {
          blurActiveElement();
          router.replace("/login");
        }}
        accessibilityRole="button"
        accessibilityLabel="Go to login"
      >
        <Text className="text-sm text-primary">Back to login</Text>
      </Pressable>
    </View>
  );
}
