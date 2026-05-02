import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  type ScheduleCycleType,
  type ScheduledJobPayload,
} from "@/lib/api/scheduledJobs";
import {
  formatDateTimeLocalInputValue,
  getNextTopOfHourLocalInputValue,
} from "@/lib/datetime";
import {
  getIntervalStartAtLocal,
  normalizeTimePoint,
  patchTimePoint,
} from "@/lib/scheduleTimePoints";

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
  const intervalStartAt = getIntervalStartAtLocal(form.time_point);
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
    if (nextCycle === "interval") {
      const nextTimePoint = normalizeTimePoint("interval", form.time_point);
      if (typeof nextTimePoint.start_at_local === "string") {
        return nextTimePoint;
      }
      return {
        ...nextTimePoint,
        start_at_local: getNextTopOfHourLocalInputValue(timeZone),
      };
    }
    return normalizeTimePoint(nextCycle, form.time_point);
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
              const weeklyTimePoint = normalizeTimePoint(
                "weekly",
                form.time_point,
              );
              const selected = weeklyTimePoint.weekday === option.value;
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
                      time_point: patchTimePoint("weekly", form.time_point, {
                        weekday: option.value,
                      }),
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
            value={String(normalizeTimePoint("monthly", form.time_point).day)}
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
                time_point: patchTimePoint("monthly", form.time_point, {
                  day: clamped,
                }),
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
            value={String(
              form.cycle_type === "interval"
                ? normalizeTimePoint("interval", form.time_point).minutes
                : normalizeTimePoint("sequential", form.time_point).minutes,
            )}
            onChangeText={(value) => {
              if (!value.trim()) {
                return;
              }
              const parsed = Number.parseInt(value, 10);
              if (!Number.isFinite(parsed)) {
                return;
              }
              onChange({
                time_point:
                  form.cycle_type === "interval"
                    ? patchTimePoint("interval", form.time_point, {
                        minutes: parsed,
                      })
                    : patchTimePoint("sequential", form.time_point, {
                        minutes: parsed,
                      }),
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
                accessibilityLabel="Start datetime (local)"
                value={startAtInputValue}
                onChangeText={(value) => {
                  isEditingStartAtRef.current = true;
                  setStartAtInputValue(value);
                  const next = normalizeTimePoint("interval", form.time_point);
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
            value={String(
              form.cycle_type === "daily"
                ? normalizeTimePoint("daily", form.time_point).time
                : form.cycle_type === "weekly"
                  ? normalizeTimePoint("weekly", form.time_point).time
                  : normalizeTimePoint("monthly", form.time_point).time,
            )}
            onChangeText={(value) =>
              onChange({
                time_point:
                  form.cycle_type === "daily"
                    ? patchTimePoint("daily", form.time_point, { time: value })
                    : form.cycle_type === "weekly"
                      ? patchTimePoint("weekly", form.time_point, {
                          time: value,
                        })
                      : patchTimePoint("monthly", form.time_point, {
                          time: value,
                        }),
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
