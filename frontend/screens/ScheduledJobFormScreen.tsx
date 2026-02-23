import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";

import { ScreenScrollView } from "@/components/layout/ScreenScrollView";
import { ScheduledJobForm } from "@/components/scheduled/ScheduledJobForm";
import { BackButton } from "@/components/ui/BackButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { ApiRequestError } from "@/lib/api/client";
import {
  createScheduledJob,
  getScheduledJob,
  type ScheduledJobPayload,
  type ScheduleCycleType,
  type ScheduleTimePoint,
  updateScheduledJob,
} from "@/lib/api/scheduledJobs";
import { localDateTimeInputToUtcIso } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { scheduledJobsHref } from "@/lib/routes";
import { toast } from "@/lib/toast";

const initialForm: ScheduledJobPayload = {
  name: "",
  agent_id: "",
  prompt: "",
  cycle_type: "daily",
  time_point: { time: "07:00" },
  enabled: true,
};

const isValidHHMM = (value: string) => {
  if (!/^\d{2}:\d{2}$/.test(value)) return false;
  const [hhRaw, mmRaw] = value.split(":");
  const hh = Number.parseInt(hhRaw, 10);
  const mm = Number.parseInt(mmRaw, 10);
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return false;
  if (hh < 0 || hh > 23) return false;
  if (mm < 0 || mm > 59) return false;
  return true;
};

const normalizeIntervalMinutes = (value: number) => {
  const clamped = Math.max(5, Math.min(1440, value));
  return Math.ceil(clamped / 5) * 5;
};

const normalizeTimePoint = (
  cycleType: ScheduleCycleType,
  timePoint: unknown,
) => {
  const current = (timePoint ?? {}) as ScheduleTimePoint;
  if (cycleType === "interval") {
    const minutes = (current as { minutes?: unknown })?.minutes;
    const startAt = (current as { start_at?: unknown })?.start_at;
    return {
      minutes:
        typeof minutes === "number" && Number.isFinite(minutes)
          ? normalizeIntervalMinutes(minutes)
          : 10,
      ...(typeof startAt === "string" && startAt.trim()
        ? { start_at: startAt.trim() }
        : {}),
    };
  }
  if (cycleType === "weekly") {
    const weekday = (current as { weekday?: unknown })?.weekday;
    const time = (current as { time?: unknown })?.time;
    return {
      weekday: typeof weekday === "number" ? weekday : 1,
      time: typeof time === "string" ? time : "07:00",
    };
  }
  if (cycleType === "monthly") {
    const day = (current as { day?: unknown })?.day;
    const time = (current as { time?: unknown })?.time;
    return {
      day: typeof day === "number" ? Math.max(1, Math.min(31, day)) : 1,
      time: typeof time === "string" ? time : "07:00",
    };
  }
  const time = (current as { time?: unknown })?.time;
  return { time: typeof time === "string" ? time : "07:00" };
};

type Snapshot = {
  name: string;
  agent_id: string;
  prompt: string;
  cycle_type: ScheduleCycleType;
  time_point: unknown;
  enabled: boolean;
};

const buildSnapshot = (form: ScheduledJobPayload): Snapshot => ({
  name: form.name.trim(),
  agent_id: form.agent_id,
  prompt: form.prompt.trim(),
  cycle_type: form.cycle_type,
  time_point: normalizeTimePoint(form.cycle_type, form.time_point),
  enabled: form.enabled,
});

export function ScheduledJobFormScreen({ jobId }: { jobId?: string }) {
  const normalizedJobId = jobId?.trim() || undefined;
  const editing = Boolean(normalizedJobId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const goBackOrHome = useCallback(
    () => backOrHome(router, scheduledJobsHref),
    [router],
  );

  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const agentOptions = useMemo(
    () =>
      agents
        .filter((agent) => agent.source === "personal")
        .map((agent) => ({ id: agent.id, name: agent.name })),
    [agents],
  );

  const [form, setForm] = useState<ScheduledJobPayload>(initialForm);
  const [saving, setSaving] = useState(false);
  const [loadingJob, setLoadingJob] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const initialSnapshotRef = useRef<Snapshot | null>(null);

  // Ensure a default agent is selected for new jobs (when possible).
  useEffect(() => {
    if (editing) return;
    if (form.agent_id) return;
    if (agentOptions.length === 0) return;
    setForm((prev) => ({ ...prev, agent_id: agentOptions[0].id }));
  }, [editing, form.agent_id, agentOptions]);

  useEffect(() => {
    if (!editing || !normalizedJobId) return;

    let cancelled = false;
    setLoadingJob(true);
    setLoadError(null);

    getScheduledJob(normalizedJobId)
      .then((found) => {
        if (cancelled) return;
        const next: ScheduledJobPayload = {
          name: found.name,
          agent_id: found.agent_id,
          prompt: found.prompt,
          cycle_type: found.cycle_type,
          time_point: normalizeTimePoint(found.cycle_type, found.time_point),
          enabled: found.enabled,
        };
        setForm(next);
        initialSnapshotRef.current = buildSnapshot(next);
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof ApiRequestError) {
          if (error.status === 404) {
            setLoadError(
              "Job not found. It may have been deleted or you don't have access.",
            );
            return;
          }
          if (error.status === 503) {
            setLoadError("A2A integration is disabled.");
            return;
          }
          setLoadError(error.message);
          return;
        }
        const message = error instanceof Error ? error.message : "Load failed.";
        setLoadError(message);
      })
      .finally(() => {
        if (cancelled) return;
        setLoadingJob(false);
      });

    return () => {
      cancelled = true;
    };
  }, [editing, normalizedJobId]);

  useEffect(() => {
    if (initialSnapshotRef.current) return;
    if (editing) return;
    // Avoid treating initial auto-fill (default agent selection) as user edits.
    if (!form.agent_id && agentOptions.length > 0) return;
    initialSnapshotRef.current = buildSnapshot(form);
  }, [editing, form, agentOptions.length]);

  const dirty = useMemo(() => {
    const initial = initialSnapshotRef.current;
    if (!initial) return false;
    const current = buildSnapshot(form);
    return JSON.stringify(current) !== JSON.stringify(initial);
  }, [form]);

  const { allowNextNavigation } = usePreventRemoveWhenDirty({ dirty });

  const validateForm = () => {
    if (!form.name.trim()) {
      toast.error("Validation failed", "Job name is required.");
      return false;
    }
    if (!form.agent_id) {
      toast.error("Validation failed", "Please select an agent.");
      return false;
    }
    if (!form.prompt.trim()) {
      toast.error("Validation failed", "Prompt is required.");
      return false;
    }
    if (form.cycle_type === "daily") {
      const time = (form.time_point as { time?: unknown })?.time;
      if (typeof time !== "string" || !time.trim()) {
        toast.error("Validation failed", "Time is required.");
        return false;
      }
      if (!isValidHHMM(time.trim())) {
        toast.error("Validation failed", "Time must be HH:MM (00:00-23:59).");
        return false;
      }
    }
    if (form.cycle_type === "weekly") {
      const weekday = (form.time_point as { weekday?: unknown })?.weekday;
      const time = (form.time_point as { time?: unknown })?.time;
      if (typeof weekday !== "number") {
        toast.error("Validation failed", "Weekday is required.");
        return false;
      }
      if (weekday < 1 || weekday > 7) {
        toast.error("Validation failed", "Weekday must be 1..7 (Mon..Sun).");
        return false;
      }
      if (typeof time !== "string" || !time.trim()) {
        toast.error("Validation failed", "Time is required.");
        return false;
      }
      if (!isValidHHMM(time.trim())) {
        toast.error("Validation failed", "Time must be HH:MM (00:00-23:59).");
        return false;
      }
    }
    if (form.cycle_type === "interval") {
      const minutes = (form.time_point as { minutes?: unknown })?.minutes;
      if (typeof minutes !== "number" || !Number.isFinite(minutes)) {
        toast.error("Validation failed", "Interval minutes is required.");
        return false;
      }

      const rawStartAt = (form.time_point as { start_at?: unknown })?.start_at;
      if (typeof rawStartAt === "string" && rawStartAt.trim()) {
        if (!localDateTimeInputToUtcIso(rawStartAt)) {
          toast.error(
            "Validation failed",
            "Start datetime must be a valid date time.",
          );
          return false;
        }
      }
    }
    if (form.cycle_type === "monthly") {
      const day = (form.time_point as { day?: unknown })?.day;
      const time = (form.time_point as { time?: unknown })?.time;
      if (typeof day !== "number") {
        toast.error("Validation failed", "Day of month is required.");
        return false;
      }
      if (day < 1 || day > 31) {
        toast.error("Validation failed", "Day of month must be 1..31.");
        return false;
      }
      if (typeof time !== "string" || !time.trim()) {
        toast.error("Validation failed", "Time is required.");
        return false;
      }
      if (!isValidHHMM(time.trim())) {
        toast.error("Validation failed", "Time must be HH:MM (00:00-23:59).");
        return false;
      }
    }
    return true;
  };

  const handleCancel = () => {
    blurActiveElement();
    goBackOrHome();
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;

    setSaving(true);
    try {
      const normalized: ScheduledJobPayload = {
        ...form,
        name: form.name.trim(),
        prompt: form.prompt.trim(),
        time_point: normalizeTimePoint(form.cycle_type, form.time_point) as any,
      };
      if (normalized.cycle_type === "interval") {
        const rawStartAt = (form.time_point as { start_at?: unknown })
          ?.start_at;
        const normalizedStartAt = localDateTimeInputToUtcIso(
          typeof rawStartAt === "string" ? rawStartAt : "",
        );
        normalized.time_point = {
          minutes: normalizeIntervalMinutes(
            Number((normalized.time_point as any)?.minutes),
          ),
          ...(normalizedStartAt ? { start_at: normalizedStartAt } : {}),
        } as any;
      }

      if (editing && normalizedJobId) {
        await updateScheduledJob(normalizedJobId, normalized);
      } else {
        await createScheduledJob(normalized);
      }
      setForm(normalized);
      initialSnapshotRef.current = buildSnapshot(normalized);
      toast.success(
        editing ? "Job updated" : "Job created",
        editing
          ? "Scheduled job updated successfully."
          : "Scheduled job created successfully.",
      );
      allowNextNavigation();
      await queryClient.invalidateQueries({
        queryKey: queryKeys.sessions.scheduledJobs(),
      });
      goBackOrHome();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      toast.error("Save failed", message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <ScreenScrollView>
      <PageHeader
        title={editing ? "Edit Job" : "New Job"}
        subtitle="Configure recurring prompts."
        rightElement={<BackButton variant="outline" onPress={handleCancel} />}
      />

      {loadingJob ? (
        <View className="mt-8 items-center">
          <Text className="text-sm text-muted">Loading job...</Text>
        </View>
      ) : loadError ? (
        <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
          <Text className="text-base font-semibold text-white">
            Unable to load job
          </Text>
          <Text className="mt-2 text-sm text-muted">{loadError}</Text>
        </View>
      ) : (
        <View className="mt-3">
          <ScheduledJobForm
            form={form}
            saving={saving}
            editing={editing}
            agentOptions={agentOptions}
            onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            showTitle={false}
          />
        </View>
      )}

      <View className="h-10" />
    </ScreenScrollView>
  );
}
