import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  type ScheduleCycleType,
  type ScheduledJobPayload,
  type ScheduleTimePoint,
} from "@/lib/api/scheduledJobs";
import {
  formatDateTimeLocalInputValue,
  getNextTopOfHourLocalInputValue,
} from "@/lib/datetime";

type AgentOption = {
  id: string;
  name: string;
};

type ScheduledJobFormProps = {
  form: ScheduledJobPayload;
  saving: boolean;
  editing: boolean;
  agentOptions: AgentOption[];
  onChange: (patch: Partial<ScheduledJobPayload>) => void;
  onSubmit: () => void;
  onCancel: () => void;
  showTitle?: boolean;
  timeZone?: string;
  isRunning?: boolean;
};

export function ScheduledJobForm({
  form,
  saving,
  editing,
  agentOptions,
  onChange,
  onSubmit,
  onCancel,
  showTitle = true,
  timeZone,
  isRunning = false,
}: ScheduledJobFormProps) {
  const intervalStartAt = (() => {
    const startAt = (form.time_point as { start_at_local?: unknown })
      ?.start_at_local;
    return typeof startAt === "string" ? startAt : "";
  })();
  const [startAtInputValue, setStartAtInputValue] = useState(() =>
    formatDateTimeLocalInputValue(intervalStartAt, timeZone),
  );
  const isEditingStartAtRef = useRef(false);

  useEffect(() => {
    if (form.cycle_type !== "interval") {
      isEditingStartAtRef.current = false;
    }
  }, [form.cycle_type]);

  useEffect(() => {
    if (isEditingStartAtRef.current) {
      return;
    }
    setStartAtInputValue(
      intervalStartAt
        ? formatDateTimeLocalInputValue(intervalStartAt, timeZone)
        : "",
    );
  }, [intervalStartAt, timeZone, form.cycle_type]);

  const cycleOptions: { value: ScheduleCycleType; label: string }[] = [
    { value: "daily", label: "Daily" },
    { value: "weekly", label: "Weekly" },
    { value: "monthly", label: "Monthly" },
    { value: "interval", label: "Interval" },
    { value: "sequential", label: "Sequential" },
  ];
  const weekdayOptions: { value: number; label: string }[] = [
    { value: 1, label: "Mon" },
    { value: 2, label: "Tue" },
    { value: 3, label: "Wed" },
    { value: 4, label: "Thu" },
    { value: 5, label: "Fri" },
    { value: 6, label: "Sat" },
    { value: 7, label: "Sun" },
  ];

  const ensureTimePoint = (nextCycle: ScheduleCycleType) => {
    const current = form.time_point as ScheduleTimePoint;
    if (nextCycle === "daily") {
      const time = (current as { time?: unknown })?.time;
      return { time: typeof time === "string" ? time : "07:00" };
    }
    if (nextCycle === "weekly") {
      const time = (current as { time?: unknown })?.time;
      const weekday = (current as { weekday?: unknown })?.weekday;
      return {
        weekday: typeof weekday === "number" ? weekday : 1,
        time: typeof time === "string" ? time : "07:00",
      };
    }
    if (nextCycle === "interval") {
      const minutes = (current as { minutes?: unknown })?.minutes;
      const startAt = (current as { start_at_local?: unknown })?.start_at_local;
      const resolvedStartAt =
        typeof startAt === "string" && startAt.trim()
          ? startAt.trim()
          : getNextTopOfHourLocalInputValue(timeZone);
      return {
        minutes: typeof minutes === "number" ? minutes : 10,
        start_at_local: resolvedStartAt,
      };
    }
    if (nextCycle === "sequential") {
      const minutes = (current as { minutes?: unknown })?.minutes;
      return {
        minutes: typeof minutes === "number" ? minutes : 10,
      };
    }
    const time = (current as { time?: unknown })?.time;
    const day = (current as { day?: unknown })?.day;
    return {
      day: typeof day === "number" ? day : 1,
      time: typeof time === "string" ? time : "07:00",
    };
  };

  const isCurrentlyRunning = Boolean(isRunning);

  const renderLabel = (text: string) => (
    <Text className="mt-4 text-[11px] font-medium uppercase tracking-wider text-slate-500">
      {text}
    </Text>
  );

  return (
    <View className="mb-4 rounded-2xl bg-surface p-5 shadow-sm">
      {isCurrentlyRunning && (
        <View className="mb-5 rounded-xl bg-primary/10 p-4 border border-primary/20">
          <Text className="text-[11px] font-medium text-primary leading-5">
            Cannot edit a job while it is currently running. Please wait for it
            to finish or disable it first.
          </Text>
        </View>
      )}

      {showTitle ? (
        <Text className="text-base font-bold text-white mb-2">
          {editing ? "Edit Job" : "Create Job"}
        </Text>
      ) : null}

      {renderLabel("Name")}
      <TextInput
        className="mt-2 rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
        value={form.name}
        onChangeText={(value) => onChange({ name: value })}
        placeholder="Daily summary"
        placeholderTextColor="#64748B"
      />

      {renderLabel("Agent")}
      <View className="mt-2 flex-row flex-wrap gap-2">
        {agentOptions.map((agent) => {
          const selected = form.agent_id === agent.id;
          return (
            <Pressable
              key={agent.id}
              className={`rounded-xl border px-3 py-2 ${
                selected
                  ? "border-primary/40 bg-primary/10"
                  : "border-white/5 bg-black/20"
              }`}
              onPress={() => onChange({ agent_id: agent.id })}
            >
              <Text
                className={`text-[11px] font-medium ${selected ? "text-primary" : "text-slate-400"}`}
              >
                {agent.name}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {renderLabel("Cycle")}
      <View className="mt-2 flex-row flex-wrap gap-2">
        {cycleOptions.map((option) => {
          const selected = form.cycle_type === option.value;
          return (
            <Pressable
              key={option.value}
              className={`rounded-xl border px-3 py-2 ${
                selected
                  ? "border-primary/40 bg-primary/10"
                  : "border-white/5 bg-black/20"
              }`}
              onPress={() =>
                onChange({
                  cycle_type: option.value,
                  time_point: ensureTimePoint(option.value),
                })
              }
            >
              <Text
                className={`text-[11px] font-medium ${selected ? "text-primary" : "text-slate-400"}`}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {form.cycle_type === "weekly" ? (
        <>
          {renderLabel("Weekday")}
          <View className="mt-2 flex-row flex-wrap gap-2">
            {weekdayOptions.map((option) => {
              const selected =
                (form.time_point as { weekday?: number })?.weekday ===
                option.value;
              return (
                <Pressable
                  key={option.value}
                  className={`rounded-xl border px-3 py-2 ${
                    selected
                      ? "border-primary/40 bg-primary/10"
                      : "border-white/5 bg-black/20"
                  }`}
                  onPress={() =>
                    onChange({
                      time_point: {
                        ...(form.time_point as any),
                        weekday: option.value,
                      },
                    })
                  }
                >
                  <Text
                    className={`text-[11px] font-medium ${selected ? "text-primary" : "text-slate-400"}`}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : null}

      {form.cycle_type === "monthly" ? (
        <>
          {renderLabel("Day of Month")}
          <TextInput
            className="mt-2 rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
            value={String((form.time_point as any)?.day ?? "")}
            onChangeText={(value) => {
              if (!value.trim()) {
                return;
              }
              const parsed = Number.parseInt(value, 10);
              if (!Number.isFinite(parsed)) {
                return;
              }
              const clamped = Math.max(1, Math.min(31, parsed));
              onChange({
                time_point: {
                  ...(form.time_point as any),
                  day: clamped,
                },
              });
            }}
            placeholder="1"
            placeholderTextColor="#64748B"
            keyboardType="number-pad"
          />
        </>
      ) : null}

      {form.cycle_type === "interval" || form.cycle_type === "sequential" ? (
        <>
          {renderLabel(
            form.cycle_type === "sequential"
              ? "Wait minutes after completion (5..1440)"
              : "Interval minutes (5..1440)",
          )}
          <TextInput
            className="mt-2 rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
            value={String((form.time_point as any)?.minutes ?? "")}
            onChangeText={(value) => {
              if (!value.trim()) {
                return;
              }
              const parsed = Number.parseInt(value, 10);
              if (!Number.isFinite(parsed)) {
                return;
              }
              const intervalStartAt = (form.time_point as any)?.start_at_local;
              const nextTimePoint: Record<string, unknown> = {
                minutes: parsed,
              };
              if (
                form.cycle_type === "interval" &&
                typeof intervalStartAt === "string" &&
                intervalStartAt.trim()
              ) {
                nextTimePoint.start_at_local = intervalStartAt;
              }
              onChange({
                time_point: nextTimePoint as any,
              });
            }}
            placeholder="10"
            placeholderTextColor="#64748B"
            keyboardType="number-pad"
          />
          {form.cycle_type === "interval" ? (
            <>
              {renderLabel("Start datetime (local) (optional)")}
              <TextInput
                className="mt-2 rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
                value={startAtInputValue}
                onChangeText={(value) => {
                  isEditingStartAtRef.current = true;
                  setStartAtInputValue(value);
                  const next = {
                    ...(form.time_point as any),
                  };
                  if (value.trim()) {
                    next.start_at_local = value.trim();
                  } else {
                    delete next.start_at_local;
                  }
                  onChange({
                    time_point: next,
                  });
                }}
                onBlur={() => {
                  isEditingStartAtRef.current = false;
                }}
                placeholder="2026-02-23T14:30"
                placeholderTextColor="#64748B"
                keyboardType="default"
              />
            </>
          ) : null}
        </>
      ) : (
        <>
          {renderLabel("Time (HH:MM)")}
          <TextInput
            className="mt-2 rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
            value={String((form.time_point as any)?.time ?? "")}
            onChangeText={(value) =>
              onChange({
                time_point: { ...(form.time_point as any), time: value },
              })
            }
            placeholder="07:00"
            placeholderTextColor="#64748B"
          />
        </>
      )}

      {renderLabel("Session Policy")}
      <View className="mt-2 flex-row flex-wrap gap-2">
        {(
          [
            { value: "new_each_run", label: "New Each Run" },
            { value: "reuse_single", label: "Reuse Single" },
          ] as const
        ).map((option) => {
          const selected = form.conversation_policy === option.value;
          return (
            <Pressable
              key={option.value}
              className={`rounded-xl border px-3 py-2 ${
                selected
                  ? "border-primary/40 bg-primary/10"
                  : "border-white/5 bg-black/20"
              }`}
              onPress={() => onChange({ conversation_policy: option.value })}
            >
              <Text
                className={`text-[11px] font-medium ${selected ? "text-primary" : "text-slate-400"}`}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {renderLabel("Prompt")}
      <TextInput
        className="mt-2 min-h-[100px] rounded-xl bg-black/40 px-3 py-2 text-sm text-white"
        multiline
        textAlignVertical="top"
        value={form.prompt}
        onChangeText={(value) => onChange({ prompt: value })}
        placeholder="Summarize key updates..."
        placeholderTextColor="#64748B"
      />

      <View className="mt-8 flex-row items-center justify-between gap-3">
        <Button
          label="Cancel"
          size="sm"
          variant="secondary"
          onPress={onCancel}
        />
        <Button
          label={editing ? "Save" : "Create"}
          size="sm"
          loading={saving}
          disabled={isCurrentlyRunning}
          onPress={onSubmit}
        />
      </View>
    </View>
  );
}
