import React from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";

const prettyJson = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return null;
  }
};

export function InterruptActionCard({
  pendingInterrupt,
  pendingInterruptCount,
  interruptAction,
  questionAnswers,
  structuredResponseInput,
  onPermissionReply,
  onPermissionsReply,
  onQuestionAnswerChange,
  onQuestionOptionPick,
  onQuestionReply,
  onQuestionReject,
  onStructuredResponseChange,
  onElicitationReply,
}: {
  pendingInterrupt: PendingRuntimeInterrupt;
  pendingInterruptCount: number;
  interruptAction: string | null;
  questionAnswers: string[];
  structuredResponseInput: string;
  onPermissionReply: (reply: "once" | "always" | "reject") => void;
  onPermissionsReply: (scope: "turn" | "session") => void;
  onQuestionAnswerChange: (index: number, value: string) => void;
  onQuestionOptionPick: (index: number, value: string) => void;
  onQuestionReply: () => void;
  onQuestionReject: () => void;
  onStructuredResponseChange: (value: string) => void;
  onElicitationReply: (action: "accept" | "decline" | "cancel") => void;
}) {
  const remainingInterruptCount = Math.max(pendingInterruptCount - 1, 0);
  const isBusy = Boolean(interruptAction);

  if (pendingInterrupt.type === "permission") {
    const permission = pendingInterrupt.details.permission ?? "unknown";
    const patterns = pendingInterrupt.details.patterns ?? [];
    const displayMessage = pendingInterrupt.details.displayMessage ?? null;
    return (
      <View className="mt-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4">
        <Text className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Permission Required
        </Text>
        {remainingInterruptCount > 0 ? (
          <Text className="mt-2 text-xs text-amber-200">
            {remainingInterruptCount} more pending request
            {remainingInterruptCount === 1 ? "" : "s"} will appear after this
            one is resolved.
          </Text>
        ) : null}
        {displayMessage ? (
          <Text className="mt-2 text-sm text-amber-50">{displayMessage}</Text>
        ) : null}
        <Text className="mt-2 text-sm text-white">
          Permission: <Text className="font-semibold">{permission}</Text>
        </Text>
        {patterns.length > 0 ? (
          <View className="mt-2 gap-1">
            {patterns.map((pattern) => (
              <Text key={pattern} className="text-xs text-amber-100">
                • {pattern}
              </Text>
            ))}
          </View>
        ) : null}
        <View className="mt-4 flex-row flex-wrap gap-2">
          <Button
            size="sm"
            label="Allow once"
            testID="interrupt-permission-once"
            loading={interruptAction === "permission:once"}
            disabled={isBusy}
            onPress={() => onPermissionReply("once")}
          />
          <Button
            size="sm"
            label="Always allow"
            testID="interrupt-permission-always"
            variant="secondary"
            loading={interruptAction === "permission:always"}
            disabled={isBusy}
            onPress={() => onPermissionReply("always")}
          />
          <Button
            size="sm"
            label="Reject"
            testID="interrupt-permission-reject"
            variant="danger"
            loading={interruptAction === "permission:reject"}
            disabled={isBusy}
            onPress={() => onPermissionReply("reject")}
          />
        </View>
      </View>
    );
  }

  if (pendingInterrupt.type === "permissions") {
    const displayMessage = pendingInterrupt.details.displayMessage ?? null;
    const requestedPermissions = prettyJson(
      pendingInterrupt.details.permissions,
    );
    return (
      <View className="mt-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4">
        <Text className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Permissions Required
        </Text>
        {remainingInterruptCount > 0 ? (
          <Text className="mt-2 text-xs text-amber-200">
            {remainingInterruptCount} more pending request
            {remainingInterruptCount === 1 ? "" : "s"} will appear after this
            one is resolved.
          </Text>
        ) : null}
        {displayMessage ? (
          <Text className="mt-2 text-sm text-amber-50">{displayMessage}</Text>
        ) : null}
        {requestedPermissions ? (
          <View className="mt-3 rounded-xl border border-white/10 bg-slate-950/50 p-3">
            <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Requested Permissions
            </Text>
            <Text className="mt-2 font-mono text-[11px] leading-5 text-slate-100">
              {requestedPermissions}
            </Text>
          </View>
        ) : null}
        <Text className="mt-3 text-xs text-amber-100">
          Edit the granted subset as JSON before submitting.
        </Text>
        <TextInput
          testID="interrupt-permissions-json-input"
          className="mt-2 min-h-[120px] rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-white"
          value={structuredResponseInput}
          editable={!isBusy}
          multiline
          placeholder='{"fileSystem":{"write":["/workspace/project"]}}'
          placeholderTextColor="#6b7280"
          onChangeText={onStructuredResponseChange}
        />
        <View className="mt-4 flex-row flex-wrap gap-2">
          <Button
            size="sm"
            label="Grant for turn"
            testID="interrupt-permissions-turn"
            loading={interruptAction === "permissions:turn"}
            disabled={isBusy}
            onPress={() => onPermissionsReply("turn")}
          />
          <Button
            size="sm"
            label="Grant for session"
            testID="interrupt-permissions-session"
            variant="secondary"
            loading={interruptAction === "permissions:session"}
            disabled={isBusy}
            onPress={() => onPermissionsReply("session")}
          />
        </View>
      </View>
    );
  }

  if (pendingInterrupt.type === "elicitation") {
    const displayMessage = pendingInterrupt.details.displayMessage ?? null;
    const requestedSchema = prettyJson(
      pendingInterrupt.details.requestedSchema,
    );
    return (
      <View className="mt-3 rounded-2xl border border-violet-500/40 bg-violet-500/10 p-4">
        <Text className="text-xs font-semibold uppercase tracking-wide text-violet-300">
          Structured Input Required
        </Text>
        {remainingInterruptCount > 0 ? (
          <Text className="mt-2 text-xs text-violet-200">
            {remainingInterruptCount} more pending request
            {remainingInterruptCount === 1 ? "" : "s"} will appear after this
            one is resolved.
          </Text>
        ) : null}
        {displayMessage ? (
          <Text className="mt-2 text-sm text-violet-50">{displayMessage}</Text>
        ) : null}
        <View className="mt-3 gap-1">
          {pendingInterrupt.details.mode ? (
            <Text className="text-xs text-violet-100">
              Mode: {pendingInterrupt.details.mode}
            </Text>
          ) : null}
          {pendingInterrupt.details.serverName ? (
            <Text className="text-xs text-violet-100">
              Server: {pendingInterrupt.details.serverName}
            </Text>
          ) : null}
          {pendingInterrupt.details.url ? (
            <Text className="text-xs text-violet-100">
              URL: {pendingInterrupt.details.url}
            </Text>
          ) : null}
        </View>
        {requestedSchema ? (
          <View className="mt-3 rounded-xl border border-white/10 bg-slate-950/50 p-3">
            <Text className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Requested Schema
            </Text>
            <Text className="mt-2 font-mono text-[11px] leading-5 text-slate-100">
              {requestedSchema}
            </Text>
          </View>
        ) : null}
        <Text className="mt-3 text-xs text-violet-100">
          Provide the accepted response as JSON.
        </Text>
        <TextInput
          testID="interrupt-elicitation-json-input"
          className="mt-2 min-h-[120px] rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-white"
          value={structuredResponseInput}
          editable={!isBusy}
          multiline
          placeholder='{"approved":true}'
          placeholderTextColor="#6b7280"
          onChangeText={onStructuredResponseChange}
        />
        <View className="mt-4 flex-row flex-wrap gap-2">
          <Button
            size="sm"
            label="Submit response"
            testID="interrupt-elicitation-accept"
            loading={interruptAction === "elicitation:accept"}
            disabled={isBusy}
            onPress={() => onElicitationReply("accept")}
          />
          <Button
            size="sm"
            label="Decline"
            testID="interrupt-elicitation-decline"
            variant="danger"
            loading={interruptAction === "elicitation:decline"}
            disabled={isBusy}
            onPress={() => onElicitationReply("decline")}
          />
          <Button
            size="sm"
            label="Cancel"
            testID="interrupt-elicitation-cancel"
            variant="secondary"
            loading={interruptAction === "elicitation:cancel"}
            disabled={isBusy}
            onPress={() => onElicitationReply("cancel")}
          />
        </View>
      </View>
    );
  }

  const questions = pendingInterrupt.details.questions ?? [];
  const displayMessage = pendingInterrupt.details.displayMessage ?? null;
  return (
    <View className="mt-3 rounded-2xl border border-sky-500/40 bg-sky-500/10 p-4">
      <Text className="text-xs font-semibold uppercase tracking-wide text-sky-300">
        Additional Input Required
      </Text>
      {remainingInterruptCount > 0 ? (
        <Text className="mt-2 text-xs text-sky-200">
          {remainingInterruptCount} more pending request
          {remainingInterruptCount === 1 ? "" : "s"} will appear after this one
          is resolved.
        </Text>
      ) : null}
      {displayMessage ? (
        <Text className="mt-2 text-sm text-sky-50">{displayMessage}</Text>
      ) : null}
      {questions.map((question, index) => {
        const answer = questionAnswers[index] ?? "";
        return (
          <View key={`${pendingInterrupt.requestId}:${index}`} className="mt-3">
            {question.header ? (
              <Text className="text-[11px] font-semibold text-sky-200">
                {question.header}
              </Text>
            ) : null}
            <Text className="mt-1 text-sm text-white">{question.question}</Text>
            {question.description ? (
              <Text className="mt-1 text-xs text-sky-100">
                {question.description}
              </Text>
            ) : null}
            <TextInput
              testID={`interrupt-question-input-${index}`}
              className="mt-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
              value={answer}
              editable={!isBusy}
              placeholder="Type your answer"
              placeholderTextColor="#6b7280"
              onChangeText={(value) => onQuestionAnswerChange(index, value)}
            />
            {question.options.length > 0 ? (
              <View className="mt-2 flex-row flex-wrap gap-2">
                {question.options.map((option) => {
                  const optionValue = option.value || option.label;
                  return (
                    <Pressable
                      key={`${pendingInterrupt.requestId}:${index}:${option.label}`}
                      className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1"
                      disabled={isBusy}
                      onPress={() => onQuestionOptionPick(index, optionValue)}
                    >
                      <Text className="text-[11px] text-slate-200">
                        {option.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : null}
          </View>
        );
      })}
      <View className="mt-4 flex-row flex-wrap gap-2">
        <Button
          size="sm"
          label="Submit answers"
          testID="interrupt-question-submit"
          loading={interruptAction === "question:reply"}
          disabled={isBusy}
          onPress={onQuestionReply}
        />
        <Button
          size="sm"
          label="Reject"
          testID="interrupt-question-reject"
          variant="danger"
          loading={interruptAction === "question:reject"}
          disabled={isBusy}
          onPress={onQuestionReject}
        />
      </View>
    </View>
  );
}
