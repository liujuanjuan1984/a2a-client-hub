import React from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";

export function InterruptActionCard({
  pendingInterrupt,
  pendingInterruptCount,
  interruptAction,
  questionAnswers,
  onPermissionReply,
  onQuestionAnswerChange,
  onQuestionOptionPick,
  onQuestionReply,
  onQuestionReject,
}: {
  pendingInterrupt: PendingRuntimeInterrupt;
  pendingInterruptCount: number;
  interruptAction: string | null;
  questionAnswers: string[];
  onPermissionReply: (reply: "once" | "always" | "reject") => void;
  onQuestionAnswerChange: (index: number, value: string) => void;
  onQuestionOptionPick: (index: number, value: string) => void;
  onQuestionReply: () => void;
  onQuestionReject: () => void;
}) {
  const remainingInterruptCount = Math.max(pendingInterruptCount - 1, 0);

  if (pendingInterrupt.type === "permission") {
    const permission = pendingInterrupt.details.permission ?? "unknown";
    const patterns = pendingInterrupt.details.patterns ?? [];
    const displayMessage = pendingInterrupt.details.displayMessage ?? null;
    return (
      <View className="mt-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4">
        <Text className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Authorization Required
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
            disabled={Boolean(interruptAction)}
            onPress={() => onPermissionReply("once")}
          />
          <Button
            size="sm"
            label="Always allow"
            testID="interrupt-permission-always"
            variant="secondary"
            loading={interruptAction === "permission:always"}
            disabled={Boolean(interruptAction)}
            onPress={() => onPermissionReply("always")}
          />
          <Button
            size="sm"
            label="Reject"
            testID="interrupt-permission-reject"
            variant="danger"
            loading={interruptAction === "permission:reject"}
            disabled={Boolean(interruptAction)}
            onPress={() => onPermissionReply("reject")}
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
              editable={!interruptAction}
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
                      disabled={Boolean(interruptAction)}
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
          disabled={Boolean(interruptAction)}
          onPress={onQuestionReply}
        />
        <Button
          size="sm"
          label="Reject"
          testID="interrupt-question-reject"
          variant="danger"
          loading={interruptAction === "question:reject"}
          disabled={Boolean(interruptAction)}
          onPress={onQuestionReject}
        />
      </View>
    </View>
  );
}
