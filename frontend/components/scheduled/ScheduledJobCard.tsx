import { useRouter } from "expo-router";
import { useState } from "react";
import { Switch, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { IconButton } from "@/components/ui/IconButton";
import {
  type IntervalTimePoint,
  type ScheduledJob,
  type ScheduledJobExecution,
} from "@/lib/api/scheduledJobs";
import { confirmAction } from "@/lib/confirm";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";

const executionStatusColor: Record<ScheduledJobExecution["status"], string> = {
  pending: "text-amber-300",
  running: "text-blue-400",
  success: "text-emerald-400",
  failed: "text-red-400",
};

const knownExecutionErrorLabels: Record<string, string> = {
  agent_unavailable: "Agent unavailable",
  outbound_not_allowed: "Outbound blocked",
  timeout: "Timeout",
  peer_protocol_error: "Peer protocol error",
  manual_failed: "Stopped manually",
};

const formatExecutionErrorCode = (
  errorCode: string | null | undefined,
): string | null => {
  if (!errorCode) return null;
  const normalized = errorCode.trim().toLowerCase();
  if (!normalized) return null;
  if (knownExecutionErrorLabels[normalized]) {
    return knownExecutionErrorLabels[normalized];
  }
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const formatDuration = (seconds: number | null | undefined): string | null => {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  if (seconds < 60) return `${Math.max(Math.floor(seconds), 1)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
};

const formatDurationBetween = (
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
): string | null => {
  if (!startedAt || !finishedAt) return null;
  const startedMs = new Date(startedAt).getTime();
  const finishedMs = new Date(finishedAt).getTime();
  if (!Number.isFinite(startedMs) || !Number.isFinite(finishedMs)) {
    return null;
  }
  return formatDuration(
    Math.max(Math.floor((finishedMs - startedMs) / 1000), 0),
  );
};

const getCardTone = (job: ScheduledJob, isReallyRunning: boolean) => {
  if (!job.enabled) {
    return {
      container: "opacity-80",
      title: "text-slate-300",
      text: "text-slate-400",
      prompt: "text-slate-400",
      statusText: "DISABLED",
      iconColor: "#475569",
      switchTrack: { false: "#1E293B", true: "#334155" },
    };
  }
  if (isReallyRunning) {
    return {
      container: "border-2 border-primary/40",
      title: "text-primary",
      text: "text-slate-300",
      prompt: "text-white",
      statusText: "RUNNING",
      iconColor: "#FACC15",
      switchTrack: { false: "#000000", true: "#FACC15" },
    };
  }
  return {
    container: "border border-white/5",
    title: "text-white",
    text: "text-slate-500",
    prompt: "text-slate-300",
    statusText: "ENABLED",
    iconColor: "#FFFFFF",
    switchTrack: { false: "#0F172A", true: "#FACC15" },
  };
};

const buildStatusHint = (job: ScheduledJob): string | null => {
  const summary = job.status_summary;
  if (!summary) return null;

  if (summary.state === "running" && summary.manual_intervention_recommended) {
    const lastHeartbeatAt = formatLocalDateTime(
      summary.last_heartbeat_at,
      job.schedule_timezone,
    );
    return lastHeartbeatAt
      ? `No heartbeat since ${lastHeartbeatAt}. Review this run before it blocks later schedules.`
      : "This run has not reported a recent heartbeat. Review whether it should be stopped.";
  }

  if (summary.state === "running") {
    const runningFor = formatDuration(summary.running_duration_seconds);
    return runningFor
      ? `Run in progress for ${runningFor}.`
      : "Run in progress.";
  }

  if (summary.state === "recent_failed") {
    const failureMessage = summary.recent_failure_message?.trim();
    const failureCodeLabel = formatExecutionErrorCode(
      summary.recent_failure_error_code,
    );
    if (failureMessage) {
      return failureCodeLabel
        ? `Last run failed (${failureCodeLabel}): ${failureMessage}`
        : `Last run failed: ${failureMessage}`;
    }
    if (failureCodeLabel) {
      return `Last run failed (${failureCodeLabel}).`;
    }
    const lastFinishedAt = formatLocalDateTime(
      summary.last_finished_at,
      job.schedule_timezone,
    );
    return lastFinishedAt
      ? `Last run failed at ${lastFinishedAt}.`
      : "Last run failed.";
  }

  return null;
};

type ScheduledJobCardProps = {
  job: ScheduledJob;
  agentName: string;
  timeZone?: string;
  executions: ScheduledJobExecution[];
  executionsOpen: boolean;
  executionsLoading: boolean;
  executionsHasMore?: boolean;
  executionsLoadingMore?: boolean;
  onToggleEnabled: () => void | Promise<void>;
  onEdit: () => void;
  onDelete?: () => void | Promise<void>;
  onMarkFailed?: () => void | Promise<void>;
  onToggleExecutions: () => void;
  onLoadMoreExecutions?: () => void;
};

export function ScheduledJobCard({
  job,
  agentName,
  timeZone,
  executions,
  executionsOpen,
  executionsLoading,
  executionsHasMore,
  executionsLoadingMore,
  onToggleEnabled,
  onEdit,
  onDelete,
  onMarkFailed,
  onToggleExecutions,
  onLoadMoreExecutions,
}: ScheduledJobCardProps) {
  const router = useRouter();
  const isReallyRunning =
    Boolean(job.is_running) || executions.some((e) => e.status === "running");
  const tone = getCardTone(job, isReallyRunning);
  const intervalTimePoint =
    job.cycle_type === "interval" &&
    typeof (job.time_point as IntervalTimePoint)?.minutes === "number"
      ? (job.time_point as IntervalTimePoint)
      : null;
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [markingFailed, setMarkingFailed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const canMarkFailed = isReallyRunning;
  const hasPrompt = Boolean(job.prompt?.trim());
  const summary = job.status_summary;
  const needsAttention =
    summary?.state === "running" && summary.manual_intervention_recommended;
  const statusHint = buildStatusHint(job);
  const stopTitle = needsAttention ? "Stop stalled job?" : "Stop running job?";
  const stopMessage = needsAttention
    ? "This run has not reported a recent heartbeat. Mark it as failed if it looks stuck or needs manual recovery."
    : "This will mark the current run as failed and stop the active schedule execution.";
  const stopConfirmLabel = needsAttention ? "Stop stalled run" : "Stop run";

  const openExecutionSession = (execution: ScheduledJobExecution) => {
    if (!execution.conversation_id) return;
    const agentId = job.agent_id;
    if (!agentId) {
      toast.error(
        "Open session failed",
        "Missing agent id for this execution.",
      );
      return;
    }

    blurActiveElement();
    router.push(buildChatRoute(agentId, execution.conversation_id));
  };

  const handleMarkFailed = async () => {
    if (!onMarkFailed || markingFailed || !canMarkFailed) return;
    const confirmed = await confirmAction({
      title: stopTitle,
      message: stopMessage,
      confirmLabel: stopConfirmLabel,
      cancelLabel: "Cancel",
      isDestructive: true,
    });
    if (!confirmed) return;
    setMarkingFailed(true);
    try {
      await onMarkFailed();
    } finally {
      setMarkingFailed(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete || deleting) return;
    const confirmed = await confirmAction({
      title: "Delete scheduled job?",
      message: "This action cannot be undone.",
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      isDestructive: true,
    });
    if (!confirmed) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <View
      className={`mb-4 rounded-2xl overflow-hidden bg-surface shadow-sm ${tone.container}`}
    >
      <View className="px-4 py-4">
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-[10px] font-semibold uppercase tracking-widest text-neo-green">
            {agentName}
          </Text>
          <View className="bg-black/20 rounded px-1.5 py-0.5">
            <Text className={`text-[10px] font-bold ${tone.text}`}>
              {tone.statusText}
            </Text>
          </View>
        </View>

        <View className="flex-row items-start justify-between">
          <View className="flex-1 pr-3">
            <Text className={`text-[13px] font-semibold ${tone.title}`}>
              {job.name}
            </Text>
            <Text className={`mt-1.5 text-[11px] font-normal ${tone.text}`}>
              {job.cycle_type} • Every {intervalTimePoint?.minutes ?? "-"} min
            </Text>
            <Text className={`mt-0.5 text-[11px] font-normal ${tone.text}`}>
              Next:{" "}
              {job.next_run_at_local ??
                formatLocalDateTime(job.next_run_at_utc, timeZone)}
            </Text>
            {statusHint ? (
              <Text
                className={`mt-1 text-[11px] font-medium leading-4 ${
                  needsAttention
                    ? "text-amber-300"
                    : summary?.state === "recent_failed"
                      ? "text-red-300"
                      : "text-slate-400"
                }`}
              >
                {statusHint}
              </Text>
            ) : null}
          </View>
          <Switch
            value={job.enabled}
            disabled={togglingEnabled}
            trackColor={tone.switchTrack}
            thumbColor="#FFFFFF"
            ios_backgroundColor="#374151"
            onValueChange={async () => {
              if (togglingEnabled) return;
              setTogglingEnabled(true);
              try {
                blurActiveElement();
                await onToggleEnabled();
              } finally {
                setTogglingEnabled(false);
              }
            }}
            accessibilityLabel={`Job enabled: ${tone.statusText}`}
          />
        </View>

        {promptExpanded && hasPrompt && (
          <View className="mt-4 pt-4 border-t border-white/5">
            <Text className={`text-[11px] leading-5 ${tone.prompt}`}>
              {job.prompt}
            </Text>
          </View>
        )}
      </View>

      <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
        <View className="flex-row items-center gap-2">
          {!canMarkFailed ? (
            <IconButton
              accessibilityLabel="Edit job"
              icon="create-outline"
              size="xs"
              variant="secondary"
              onPress={onEdit}
            />
          ) : null}
          <IconButton
            accessibilityLabel={
              promptExpanded ? "Collapse prompt" : "Expand prompt"
            }
            icon={promptExpanded ? "chevron-up" : "chevron-down"}
            size="xs"
            variant="secondary"
            onPress={() => setPromptExpanded(!promptExpanded)}
          />
          {hasPrompt ? (
            <CopyButton
              value={job.prompt}
              successMessage="Prompt copied to clipboard."
              accessibilityLabel="Copy prompt"
              variant="ghost"
              size="xs"
              iconColor={tone.iconColor}
            />
          ) : null}
          <IconButton
            accessibilityLabel={
              executionsOpen
                ? "Hide execution history"
                : "Show execution history"
            }
            icon={executionsOpen ? "time" : "time-outline"}
            size="xs"
            variant={executionsOpen ? "primary" : "secondary"}
            onPress={onToggleExecutions}
          />
        </View>

        <View className="flex-row items-center gap-2">
          {canMarkFailed ? (
            <Button
              label={needsAttention ? "Stop stalled run" : "Stop run"}
              size="xs"
              variant="danger"
              className="bg-red-500/40"
              loading={markingFailed}
              disabled={!onMarkFailed}
              onPress={handleMarkFailed}
            />
          ) : null}
          {!canMarkFailed ? (
            <IconButton
              accessibilityLabel="Delete job"
              icon="trash-outline"
              size="xs"
              variant="danger"
              className="bg-red-500/40"
              loading={deleting}
              disabled={!onDelete}
              onPress={handleDelete}
            />
          ) : null}
        </View>
      </View>

      {executionsOpen ? (
        <View className="bg-black/10 px-4 pb-4 pt-1">
          <View className="rounded-xl bg-black/20 p-4">
            {executionsLoading ? (
              <Text className="text-[11px] font-medium text-slate-500">
                Loading history...
              </Text>
            ) : executions.length === 0 ? (
              <Text className="text-[11px] font-medium text-slate-500">
                No executions yet.
              </Text>
            ) : (
              <>
                {executions.map((execution) => {
                  const errorMessage = execution.error_message?.trim();
                  const errorCodeLabel = formatExecutionErrorCode(
                    execution.error_code,
                  );
                  const scheduledAt = formatLocalDateTime(
                    execution.scheduled_for,
                    timeZone,
                  );
                  const hasStartedAt = Boolean(execution.started_at);
                  const startedAt = hasStartedAt
                    ? formatLocalDateTime(execution.started_at, timeZone)
                    : null;
                  const hasFinishedAt = Boolean(execution.finished_at);
                  const finishedAt = hasFinishedAt
                    ? formatLocalDateTime(execution.finished_at, timeZone)
                    : null;
                  const hasLastHeartbeatAt = Boolean(
                    execution.last_heartbeat_at,
                  );
                  const lastHeartbeatAt = hasLastHeartbeatAt
                    ? formatLocalDateTime(execution.last_heartbeat_at, timeZone)
                    : null;
                  const duration = formatDurationBetween(
                    execution.started_at,
                    execution.finished_at,
                  );

                  return (
                    <View
                      key={execution.id}
                      className="mb-2 rounded-xl bg-black/20 p-3"
                    >
                      <View className="flex-row items-center justify-between gap-3">
                        <View className="min-w-0 flex-1 flex-row items-center gap-2">
                          <View className="rounded bg-black/20 px-1 py-0.5">
                            <Text
                              className={`text-[9px] font-bold ${executionStatusColor[execution.status]}`}
                            >
                              {execution.status.toUpperCase()}
                            </Text>
                          </View>
                          <Text className="flex-1 text-[10px] font-medium text-slate-500">
                            {formatLocalDateTime(
                              execution.finished_at ??
                                execution.started_at ??
                                execution.scheduled_for,
                              timeZone,
                            )}
                          </Text>
                        </View>
                        {execution.conversation_id ? (
                          <Button
                            label="Open Session"
                            size="xs"
                            variant="secondary"
                            onPress={() => openExecutionSession(execution)}
                          />
                        ) : null}
                      </View>
                      {errorMessage ? (
                        <Text className="mt-2 text-[11px] font-normal leading-4 text-red-400/80">
                          {errorMessage}
                        </Text>
                      ) : null}
                      {errorCodeLabel ? (
                        <View className="mt-2 self-start rounded bg-red-500/10 px-2 py-1">
                          <Text className="text-[10px] font-semibold text-red-300">
                            {errorCodeLabel}
                          </Text>
                        </View>
                      ) : null}
                      <View className="mt-2 gap-1">
                        <Text className="text-[10px] font-medium text-slate-500">
                          Scheduled: {scheduledAt ?? "-"}
                        </Text>
                        {startedAt ? (
                          <Text className="text-[10px] font-medium text-slate-500">
                            Started: {startedAt}
                          </Text>
                        ) : null}
                        {finishedAt ? (
                          <Text className="text-[10px] font-medium text-slate-500">
                            Finished: {finishedAt}
                          </Text>
                        ) : null}
                        {duration ? (
                          <Text className="text-[10px] font-medium text-slate-500">
                            Duration: {duration}
                          </Text>
                        ) : null}
                        {!hasFinishedAt && lastHeartbeatAt ? (
                          <Text className="text-[10px] font-medium text-slate-500">
                            Last heartbeat: {lastHeartbeatAt}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                  );
                })}

                {executionsHasMore ? (
                  <Button
                    className="mt-2 self-start"
                    label={executionsLoadingMore ? "Loading..." : "More"}
                    size="xs"
                    variant="secondary"
                    loading={executionsLoadingMore}
                    onPress={onLoadMoreExecutions}
                  />
                ) : null}
              </>
            )}
          </View>
        </View>
      ) : null}
    </View>
  );
}
