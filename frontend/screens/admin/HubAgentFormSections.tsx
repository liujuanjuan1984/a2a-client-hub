import type { ReactNode } from "react";
import { Pressable, Switch, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { KeyValueInputRow } from "@/components/ui/KeyValueInputRow";
import type {
  HubA2AAuthType,
  HubA2AAvailabilityPolicy,
} from "@/lib/api/hubA2aAgentsAdmin";
import type {
  HubAgentFormErrors,
  HubAgentFormValues,
} from "@/screens/admin/hubAgentFormState";
import type { HeaderRow } from "@/screens/admin/hubAgentFormUtils";

const authTypes: { label: string; value: HubA2AAuthType }[] = [
  { label: "No Auth", value: "none" },
  { label: "Bearer", value: "bearer" },
];

const policies: { label: string; value: HubA2AAvailabilityPolicy }[] = [
  { label: "Public", value: "public" },
  { label: "Allowlist", value: "allowlist" },
];

type HubAgentFormSectionsProps = {
  values: HubAgentFormValues;
  errors: HubAgentFormErrors;
  disableEnabledToggle?: boolean;
  availabilityDescription?: string;
  availabilityHintWhenAllowlist?: string;
  authenticationDescription?: string;
  tokenLabel: string;
  tokenPlaceholder: string;
  tokenFootnote?: ReactNode;
  extraHeadersDescription?: string;
  onNameChange: (value: string) => void;
  onCardUrlChange: (value: string) => void;
  onEnabledChange: (value: boolean) => void;
  onAvailabilityPolicyChange: (value: HubA2AAvailabilityPolicy) => void;
  onAuthTypeChange: (value: HubA2AAuthType) => void;
  onAuthHeaderChange: (value: string) => void;
  onAuthSchemeChange: (value: string) => void;
  onTokenChange: (value: string) => void;
  onTagsTextChange: (value: string) => void;
  onHeaderRowChange: (
    id: string,
    field: "key" | "value",
    value: string,
  ) => void;
  onHeaderRowRemove: (id: string) => void;
  onHeaderRowAdd: () => void;
};

export function HubAgentFormSections({
  values,
  errors,
  disableEnabledToggle = false,
  availabilityDescription,
  availabilityHintWhenAllowlist,
  authenticationDescription,
  tokenLabel,
  tokenPlaceholder,
  tokenFootnote,
  extraHeadersDescription,
  onNameChange,
  onCardUrlChange,
  onEnabledChange,
  onAvailabilityPolicyChange,
  onAuthTypeChange,
  onAuthHeaderChange,
  onAuthSchemeChange,
  onTokenChange,
  onTagsTextChange,
  onHeaderRowChange,
  onHeaderRowRemove,
  onHeaderRowAdd,
}: HubAgentFormSectionsProps) {
  return (
    <>
      <View className="rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
        <Text className="text-base font-semibold text-white">Basics</Text>
        <View className="mt-4 gap-3">
          <Input
            label="Name"
            placeholder="Agent name"
            value={values.name}
            onChangeText={onNameChange}
            error={errors.name}
          />
          <Input
            label="Agent Card URL"
            placeholder="https://agent.example.com/.well-known/agent.json"
            autoCapitalize="none"
            value={values.cardUrl}
            onChangeText={onCardUrlChange}
            error={errors.cardUrl}
          />

          <View className="flex-row items-center justify-between">
            <Text className="text-sm font-medium text-white">Enabled</Text>
            <Switch
              value={values.enabled}
              disabled={disableEnabledToggle}
              trackColor={{ false: "#334155", true: "#5c6afb" }}
              thumbColor={values.enabled ? "#ffffff" : "#e2e8f0"}
              ios_backgroundColor="#334155"
              onValueChange={onEnabledChange}
              accessibilityLabel={`Enabled: ${values.enabled ? "on" : "off"}`}
            />
          </View>
        </View>
      </View>

      <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
        <Text className="text-base font-semibold text-white">Availability</Text>
        {availabilityDescription ? (
          <Text className="mt-2 text-sm text-muted">
            {availabilityDescription}
          </Text>
        ) : null}
        <View className="mt-4 flex-row flex-wrap gap-2">
          {policies.map((option) => (
            <Pressable
              key={option.value}
              className={`rounded-full border px-4 py-2 ${
                values.availabilityPolicy === option.value
                  ? "border-primary bg-primary/20"
                  : "border-slate-700"
              }`}
              onPress={() => onAvailabilityPolicyChange(option.value)}
              accessibilityRole="button"
              accessibilityLabel={option.label}
            >
              <Text className="text-xs text-white">{option.label}</Text>
            </Pressable>
          ))}
        </View>
        {values.availabilityPolicy === "allowlist" &&
        availabilityHintWhenAllowlist ? (
          <Text className="mt-3 text-xs text-muted">
            {availabilityHintWhenAllowlist}
          </Text>
        ) : null}
      </View>

      <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
        <Text className="text-base font-semibold text-white">
          Authentication
        </Text>
        {authenticationDescription ? (
          <Text className="mt-2 text-sm text-muted">
            {authenticationDescription}
          </Text>
        ) : null}
        <View className="mt-4 flex-row flex-wrap gap-2">
          {authTypes.map((option) => (
            <Pressable
              key={option.value}
              className={`rounded-full border px-4 py-2 ${
                values.authType === option.value
                  ? "border-primary bg-primary/20"
                  : "border-slate-700"
              }`}
              onPress={() => onAuthTypeChange(option.value)}
              accessibilityRole="button"
              accessibilityLabel={option.label}
            >
              <Text className="text-xs text-white">{option.label}</Text>
            </Pressable>
          ))}
        </View>

        {values.authType === "bearer" ? (
          <View className="mt-4 gap-3">
            <Input
              label="Auth header"
              placeholder="Authorization"
              value={values.authHeader}
              onChangeText={onAuthHeaderChange}
            />
            <Input
              label="Auth scheme"
              placeholder="Bearer"
              value={values.authScheme}
              onChangeText={onAuthSchemeChange}
            />
            <Input
              label={tokenLabel}
              placeholder={tokenPlaceholder}
              secureTextEntry
              value={values.token}
              onChangeText={onTokenChange}
            />
            {tokenFootnote}
          </View>
        ) : null}
      </View>

      <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
        <Text className="text-base font-semibold text-white">Metadata</Text>
        <View className="mt-4 gap-3">
          <Input
            label="Tags (comma separated)"
            placeholder="e.g., coding, internal, opencode"
            value={values.tagsText}
            onChangeText={onTagsTextChange}
            autoCapitalize="none"
          />
        </View>
      </View>

      <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
        <Text className="text-base font-semibold text-white">
          Extra headers
        </Text>
        {extraHeadersDescription ? (
          <Text className="mt-2 text-sm text-muted">
            {extraHeadersDescription}
          </Text>
        ) : null}
        <View className="mt-4 gap-3">
          {values.extraHeaders.map((row: HeaderRow) => (
            <KeyValueInputRow
              key={row.id}
              keyValue={row.key}
              valueValue={row.value}
              onChangeKey={(value) => onHeaderRowChange(row.id, "key", value)}
              onChangeValue={(value) =>
                onHeaderRowChange(row.id, "value", value)
              }
              onRemove={() => onHeaderRowRemove(row.id)}
            />
          ))}
          <Button
            className="self-start"
            label="Add header"
            variant="outline"
            size="sm"
            onPress={onHeaderRowAdd}
          />
        </View>
      </View>
    </>
  );
}
