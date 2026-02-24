import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Switch, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
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
  running: "text-blue-300",
  success: "text-emerald-300",
  failed: "text-red-300",
};

const getCardTone = (job: ScheduledJob) => {
  if (!job.enabled) {
    return {
      container: "border-slate-800 bg-slate-900/10 grayscale",
      title: "text-slate-500",
      text: "text-slate-500",
      prompt: "text-slate-600",
      statusText: "Disabled",
      iconColor: "#64748b",
      switchTrack: { false: "#334155", true: "#475569" },
    };
  }
  if (job.last_run_status === "running") {
    return {
      container: "border-blue-500/50 bg-blue-900/20",
      title: "text-blue-100",
      text: "text-blue-200/80",
      prompt: "text-blue-200/90",
      statusText: "Running",
      iconColor: "#93c5fd",
      switchTrack: { false: "#334155", true: "#3b82f6" },
    };
  }
  return {
    container: "border-slate-800 bg-slate-900/30",
    title: "text-white",
    text: "text-slate-400",
    prompt: "text-slate-300",
    statusText: "Enabled",
    iconColor: "#94a3b8",
    switchTrack: { false: "#334155", true: "#5c6afb" },
  };
};

type ScheduledJobCardProps = {
  job: ScheduledJob;
  agentName: string;
  executions: ScheduledJobExecution[];
  executionsOpen: boolean;
  executionsLoading: boolean;
  executionsHasMore?: boolean;
  executionsLoadingMore?: boolean;
  onToggleEnabled: () => void | Promise<void>;
  onEdit: () => void;
  onMarkFailed?: () => void | Promise<void>;
  onToggleExecutions: () => void;
  onLoadMoreExecutions?: () => void;
};

export function ScheduledJobCard({
  job,
  agentName,
  executions,
  executionsOpen,
  executionsLoading,
  executionsHasMore,
  executionsLoadingMore,
  onToggleEnabled,
  onEdit,
  onMarkFailed,
  onToggleExecutions,
  onLoadMoreExecutions,
}: ScheduledJobCardProps) {
  const router = useRouter();
  const tone = getCardTone(job);
  const historyLabel = executionsOpen ? "Hide" : "History";
  const historyIcon = executionsOpen ? "time" : "time-outline";
  const intervalTimePoint =
    job.cycle_type === "interval" &&
    typeof (job.time_point as IntervalTimePoint)?.minutes === "number"
      ? (job.time_point as IntervalTimePoint)
      : null;
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [markingFailed, setMarkingFailed] = useState(false);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const canMarkFailed = job.last_run_status === "running";

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
      title: "Stop running job?",
      message:
        "This will mark the running job as failed to release resources or recover from abnormal states.",
      confirmLabel: "Stop Running",
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

  return (
    <View
      className={`mb-4 overflow-hidden rounded-2xl border ${tone.container}`}
    >
      <View className="p-4">
        <View className="flex-row items-start justify-between">
          <View className="flex-1 pr-3">
            <Text className={`text-base font-semibold ${tone.title}`}>
              {job.name}
            </Text>
            <Text className={`mt-1 text-xs ${tone.text}`}>
              Agent: {agentName}
            </Text>
            <Text className={`mt-1 text-xs ${tone.text}`}>
              {job.cycle_type}
            </Text>
            {intervalTimePoint ? (
              <Text className={`mt-1 text-xs ${tone.text}`}>
                Interval: every {intervalTimePoint.minutes} min, start{" "}
                {formatLocalDateTime(intervalTimePoint.start_at)}
              </Text>
            ) : null}
            <Text className={`mt-1 text-xs ${tone.text}`}>
              Next: {formatLocalDateTime(job.next_run_at)}
            </Text>
            <Text className={`mt-1 text-xs ${tone.text}`}>
              Last: {formatLocalDateTime(job.last_run_at)} (
              {job.last_run_status ?? "-"})
            </Text>
          </View>
          <View className="flex-row items-center gap-2">
            <Text className={`text-xs font-semibold ${tone.title}`}>
              {tone.statusText}
            </Text>
            <Switch
              value={job.enabled}
              disabled={togglingEnabled}
              trackColor={tone.switchTrack}
              thumbColor={job.enabled ? "#ffffff" : "#e2e8f0"}
              ios_backgroundColor="#334155"
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
        </View>

        <Text
          className={`mt-3 text-xs ${tone.prompt}`}
          numberOfLines={promptExpanded ? undefined : 2}
        >
          {job.prompt}
        </Text>
        <View className="mt-1 items-end">
          <Pressable
            className="rounded px-1 py-1 active:bg-slate-800/30"
            onPress={() => setPromptExpanded((value) => !value)}
            accessibilityRole="button"
            accessibilityLabel="Toggle prompt expansion"
          >
            <Text className={`text-xs font-medium ${tone.text}`}>
              {promptExpanded ? "Show less" : "Read more"}
            </Text>
          </Pressable>
        </View>
      </View>

      <View className="flex-row items-center justify-start gap-3 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
        <Pressable
          className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
          onPress={onEdit}
          accessibilityRole="button"
          accessibilityLabel="Edit"
          accessibilityHint="Edit this scheduled job"
        >
          <Ionicons name="create-outline" size={14} color={tone.iconColor} />
          <Text className={`text-xs font-medium ${tone.text}`}>Edit</Text>
        </Pressable>

        <Pressable
          className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
          onPress={onToggleExecutions}
          accessibilityRole="button"
          accessibilityLabel={historyLabel}
          accessibilityHint={`${historyLabel} execution history`}
        >
          <Ionicons name={historyIcon} size={14} color={tone.iconColor} />
          <Text className={`text-xs font-medium ${tone.text}`}>
            {historyLabel}
          </Text>
        </Pressable>

        {canMarkFailed ? (
          <Button
            className="ml-auto"
            label="Stop Running"
            size="xs"
            variant="danger"
            loading={markingFailed}
            disabled={!onMarkFailed}
            onPress={handleMarkFailed}
          />
        ) : null}
      </View>

      {executionsOpen ? (
        <View className="px-4 pb-4 pt-3">
          <View className="rounded-xl border border-slate-700 bg-slate-900/80 p-3">
            {executionsLoading ? (
              <Text className="text-xs text-muted">Loading history...</Text>
            ) : executions.length === 0 ? (
              <Text className="text-xs text-muted">No executions yet.</Text>
            ) : (
              <>
                {executions.map((execution) => (
                  <View
                    key={execution.id}
                    className="mb-2 rounded-lg border border-slate-700 p-2"
                  >
                    <View className="flex-row items-center justify-between">
                      <Text className="text-xs text-slate-300">
                        {formatLocalDateTime(
                          execution.finished_at ??
                            execution.started_at ??
                            execution.scheduled_for,
                        )}
                      </Text>
                      <Text
                        className={`text-xs font-semibold ${executionStatusColor[execution.status]}`}
                      >
                        {execution.status}
                      </Text>
                    </View>
                    {execution.error_message ? (
                      <Text className="mt-1 text-xs text-red-300">
                        {execution.error_message}
                      </Text>
                    ) : null}
                    {execution.conversation_id ? (
                      <Button
                        className="mt-2 self-start"
                        label="Open Session"
                        size="xs"
                        variant="outline"
                        onPress={() => openExecutionSession(execution)}
                      />
                    ) : null}
                  </View>
                ))}

                {executionsHasMore ? (
                  <Button
                    className="mt-2 self-start"
                    label={
                      executionsLoadingMore ? "Loading..." : "Load more history"
                    }
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
