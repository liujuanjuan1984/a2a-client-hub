import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  type ScheduleCycleType,
  type ScheduledJobPayload,
  type ScheduleTimePoint,
} from "@/lib/api/scheduledJobs";
import { formatDateTimeLocalInputValue } from "@/lib/datetime";

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
}: ScheduledJobFormProps) {
  const intervalStartAt = (() => {
    const startAt = (form.time_point as { start_at?: unknown })?.start_at;
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
      const startAt = (current as { start_at?: unknown })?.start_at;
      return {
        minutes: typeof minutes === "number" ? minutes : 10,
        ...(typeof startAt === "string" && startAt.trim()
          ? { start_at: startAt }
          : {}),
      };
    }
    const time = (current as { time?: unknown })?.time;
    const day = (current as { day?: unknown })?.day;
    return {
      day: typeof day === "number" ? day : 1,
      time: typeof time === "string" ? time : "07:00",
    };
  };

  return (
    <View className="mb-4 rounded-3xl border border-slate-800 bg-slate-900/40 p-4">
      {showTitle ? (
        <Text className="text-sm font-semibold text-white">
          {editing ? "Edit Job" : "Create Job"}
        </Text>
      ) : null}

      <Text className="mt-3 text-xs text-muted">Name</Text>
      <TextInput
        className="mt-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
        value={form.name}
        onChangeText={(value) => onChange({ name: value })}
        placeholder="Daily summary"
        placeholderTextColor="#64748b"
      />

      <Text className="mt-3 text-xs text-muted">Agent</Text>
      <View className="mt-1 flex-row flex-wrap gap-2">
        {agentOptions.map((agent) => {
          const selected = form.agent_id === agent.id;
          return (
            <Pressable
              key={agent.id}
              className={`rounded-lg border px-2 py-1 ${
                selected
                  ? "border-primary bg-primary/20"
                  : "border-slate-700 bg-slate-900"
              }`}
              onPress={() => onChange({ agent_id: agent.id })}
            >
              <Text
                className={`text-xs ${selected ? "text-primary" : "text-slate-300"}`}
              >
                {agent.name}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Text className="mt-3 text-xs text-muted">Cycle</Text>
      <View className="mt-1 flex-row flex-wrap gap-2">
        {cycleOptions.map((option) => {
          const selected = form.cycle_type === option.value;
          return (
            <Pressable
              key={option.value}
              className={`rounded-lg border px-2 py-1 ${
                selected
                  ? "border-primary bg-primary/20"
                  : "border-slate-700 bg-slate-900"
              }`}
              onPress={() =>
                onChange({
                  cycle_type: option.value,
                  time_point: ensureTimePoint(option.value),
                })
              }
            >
              <Text
                className={`text-xs ${selected ? "text-primary" : "text-slate-300"}`}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {form.cycle_type === "weekly" ? (
        <>
          <Text className="mt-3 text-xs text-muted">Weekday</Text>
          <View className="mt-1 flex-row flex-wrap gap-2">
            {weekdayOptions.map((option) => {
              const selected =
                (form.time_point as { weekday?: number })?.weekday ===
                option.value;
              return (
                <Pressable
                  key={option.value}
                  className={`rounded-lg border px-2 py-1 ${
                    selected
                      ? "border-primary bg-primary/20"
                      : "border-slate-700 bg-slate-900"
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
                    className={`text-xs ${selected ? "text-primary" : "text-slate-300"}`}
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
          <Text className="mt-3 text-xs text-muted">Day of Month</Text>
          <TextInput
            className="mt-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
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
            placeholderTextColor="#64748b"
            keyboardType="number-pad"
          />
        </>
      ) : null}

      {form.cycle_type === "interval" ? (
        <>
          <Text className="mt-3 text-xs text-muted">
            Interval minutes (5..1440)
          </Text>
          <TextInput
            className="mt-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            value={String((form.time_point as any)?.minutes ?? "")}
            onChangeText={(value) => {
              if (!value.trim()) {
                return;
              }
              const parsed = Number.parseInt(value, 10);
              if (!Number.isFinite(parsed)) {
                return;
              }
              onChange({
                time_point: {
                  ...(form.time_point as any),
                  minutes: parsed,
                },
              });
            }}
            placeholder="10"
            placeholderTextColor="#64748b"
            keyboardType="number-pad"
          />
          <Text className="mt-3 text-xs text-muted">
            Start datetime (local) (optional)
          </Text>
          <TextInput
            className="mt-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            value={startAtInputValue}
            onChangeText={(value) => {
              isEditingStartAtRef.current = true;
              setStartAtInputValue(value);
              const next = {
                ...(form.time_point as any),
              };
              if (value.trim()) {
                next.start_at = value.trim();
              } else {
                delete next.start_at;
              }
              onChange({
                time_point: next,
              });
            }}
            onBlur={() => {
              isEditingStartAtRef.current = false;
            }}
            placeholder="2026-02-23T14:30"
            placeholderTextColor="#64748b"
            keyboardType="default"
          />
        </>
      ) : (
        <>
          <Text className="mt-3 text-xs text-muted">Time (HH:MM)</Text>
          <TextInput
            className="mt-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            value={String((form.time_point as any)?.time ?? "")}
            onChangeText={(value) =>
              onChange({
                time_point: { ...(form.time_point as any), time: value },
              })
            }
            placeholder="07:00"
            placeholderTextColor="#64748b"
          />
        </>
      )}

      <Text className="mt-3 text-xs text-muted">Prompt</Text>
      <TextInput
        className="mt-1 min-h-[100px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
        multiline
        textAlignVertical="top"
        value={form.prompt}
        onChangeText={(value) => onChange({ prompt: value })}
        placeholder="Summarize key updates in the last 24 hours..."
        placeholderTextColor="#64748b"
      />

      <View className="mt-4 flex-row items-center justify-between gap-3">
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
          onPress={onSubmit}
        />
      </View>
    </View>
  );
}
