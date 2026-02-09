import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useLogin } from "@/hooks/useAuth";
import { ApiRequestError } from "@/lib/api/client";
import { blurActiveElement } from "@/lib/focus";

export function LoginScreen() {
  const login = useLogin();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleLogin = () => {
    if (!email || !password || login.isPending) {
      return;
    }
    login.mutate({ email, password });
  };

  const errorMessage =
    login.error instanceof ApiRequestError
      ? login.error.message
      : login.error instanceof Error
        ? login.error.message
        : null;

  return (
    <View className="flex-1 bg-background px-6 pt-20">
      <Text className="text-3xl font-semibold text-white">Welcome back</Text>
      <Text className="mt-2 text-base text-muted">
        Sign in to manage your A2A agents.
      </Text>

      <View className="mt-10 gap-4">
        <Input
          label="Email"
          placeholder="you@example.com"
          autoCapitalize="none"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
        />

        <Input
          label="Password"
          placeholder="••••••••"
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />
      </View>

      <Button
        className="mt-8"
        label={login.isPending ? "Signing in..." : "Sign In"}
        onPress={handleLogin}
        disabled={!email || !password}
        loading={login.isPending}
      />

      {errorMessage ? (
        <Text className="mt-4 text-sm text-accent">{errorMessage}</Text>
      ) : null}
      <View className="mt-6 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
        <Text className="text-sm text-muted">
          Need an invite? Contact Helen to request an invitation code.
        </Text>
      </View>

      <Button
        className="mt-4"
        label="Register"
        variant="secondary"
        onPress={() => {
          blurActiveElement();
          router.push("/register");
        }}
      />
    </View>
  );
}
