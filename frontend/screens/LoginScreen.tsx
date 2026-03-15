import { useState } from "react";
import { Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { AUTH_PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useLogin } from "@/hooks/useAuth";
import { getFriendlyAuthErrorMessage } from "@/lib/authErrorMessage";
import { AllowlistError } from "@/lib/api/client";
import { ENV } from "@/lib/config";

export function LoginScreen() {
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleLogin = () => {
    if (!email || !password || login.isPending) {
      return;
    }
    login.mutate({ email, password });
  };

  const errorMessage = getFriendlyAuthErrorMessage(login.error);

  return (
    <ScreenContainer topOffset={AUTH_PAGE_TOP_OFFSET}>
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
        <>
          <Text className="mt-4 text-sm text-accent">{errorMessage}</Text>
          {login.error instanceof AllowlistError && (
            <Button
              className="mt-4"
              variant="outline"
              label="Show me how to add it"
              onPress={() => {
                // TODO: Implement actual allowlist addition logic
                console.log('Action: Show instructions for allowlist', login.error.unauthorizedHost);
                alert(`To allow connections to "${login.error.unauthorizedHost}", you need to add it to your application's allowed server list. This usually involves updating the 'EXPO_PUBLIC_API_ALLOWLIST' environment variable in your project configuration. For further details, please refer to the project documentation on configuring API hosts.`);
                // In a real app, you might trigger a deep link here to guide the user to their config or a settings screen.
              }}
            />
          )}
        </>
      ) : null}
      <View className="mt-6 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
        <Text className="text-sm text-muted">
          Registration is invitation-only. Use your invitation link to register.
        </Text>
      </View>
    </ScreenContainer>
  );
}
