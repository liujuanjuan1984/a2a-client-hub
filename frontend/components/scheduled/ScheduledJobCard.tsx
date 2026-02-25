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
  running: "text-blue-400",
  success: "text-emerald-400",
  failed: "text-red-400",
};

const getCardTone = (job: ScheduledJob) => {
  if (!job.enabled) {
    return {
      container: "border-neo border-gray-600 bg-gray-800/50",
      title: "text-gray-500",
      text: "text-gray-500",
      prompt: "text-gray-600",
      statusText: "Disabled",
      iconColor: "#4b5563",
      switchTrack: { false: "#374151", true: "#4b5563" },
    };
  }
  if (job.last_run_status === "running") {
    return {
      container: "border-neo border-white bg-neo-yellow shadow-neo",
      title: "text-black",
      text: "text-black",
      prompt: "text-black",
      statusText: "Running",
      iconColor: "#000000",
      switchTrack: { false: "#000000", true: "#000000" },
    };
  }
  return {
    container: "border-neo border-white bg-surface shadow-neo",
    title: "text-white",
    text: "text-white",
    prompt: "text-white font-bold",
    statusText: "Enabled",
    iconColor: "#FFFFFF",
    switchTrack: { false: "#374151", true: "#FFDE03" },
  };
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
    <View className={`mb-6 border ${tone.container}`}>
      <View className="p-4">
        <View className="flex-row items-start justify-between">
          <View className="flex-1 pr-3">
            <Text className={`text-base font-bold ${tone.title}`}>
              {job.name}
            </Text>
            <Text className={`mt-1 text-xs font-bold ${tone.text}`}>
              Agent: {agentName}
            </Text>
            <Text className={`mt-1 text-xs font-bold ${tone.text}`}>
              Type: {job.cycle_type}
            </Text>
            {intervalTimePoint ? (
              <Text className={`mt-1 text-xs font-bold ${tone.text}`}>
                Interval: every {intervalTimePoint.minutes} min
              </Text>
            ) : null}
            <Text className={`mt-1 text-xs font-bold ${tone.text}`}>
              Next: {formatLocalDateTime(job.next_run_at, timeZone)}
            </Text>
            <Text className={`mt-1 text-xs font-bold ${tone.text}`}>
              Last: {formatLocalDateTime(job.last_run_at, timeZone)} (
              {job.last_run_status ?? "-"})
            </Text>
          </View>
          <View className="flex-row items-center gap-2">
            <Text className={`text-xs font-bold ${tone.title}`}>
              {tone.statusText}
            </Text>
            <Switch
              value={job.enabled}
              disabled={togglingEnabled}
              trackColor={tone.switchTrack}
              thumbColor={job.enabled ? "#FFFFFF" : "#FFFFFF"}
              ios_backgroundColor="#d1d5db"
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
            className="border border-white bg-surface px-2 py-0.5 active:bg-neo-yellow"
            onPress={() => setPromptExpanded((value) => !value)}
            accessibilityRole="button"
            accessibilityLabel="Toggle prompt expansion"
          >
            <Text className={`text-[10px] font-bold ${tone.text}`}>
              {promptExpanded ? "Show less" : "Read more"}
            </Text>
          </Pressable>
        </View>
      </View>

      <View className="flex-row items-center justify-start gap-3 border-t-2 border-white bg-black/20 px-4 py-3">
        <Pressable
          className="flex-row items-center gap-1 border border-white bg-surface px-3 py-2 active:bg-neo-yellow"
          onPress={onEdit}
          accessibilityRole="button"
          accessibilityLabel="Edit"
          accessibilityHint="Edit this scheduled job"
        >
          <Ionicons name="create-outline" size={14} color={tone.iconColor} />
          <Text className={`text-xs font-bold ${tone.title}`}>Edit</Text>
        </Pressable>

        <Pressable
          className="flex-row items-center gap-1 border border-white bg-surface px-3 py-2 active:bg-neo-yellow"
          onPress={onToggleExecutions}
          accessibilityRole="button"
          accessibilityLabel={historyLabel}
          accessibilityHint={`${historyLabel} execution history`}
        >
          <Ionicons name={historyIcon} size={14} color={tone.iconColor} />
          <Text className={`text-xs font-bold ${tone.title}`}>{historyLabel}</Text>
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
          <View className="border-2 border-white bg-surface p-3 shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]">
            {executionsLoading ? (
              <Text className="text-xs font-bold text-white">
                Loading history...
              </Text>
            ) : executions.length === 0 ? (
              <Text className="text-xs font-bold text-white">
                No executions yet.
              </Text>
            ) : (
              <>
                {executions.map((execution) => (
                  <View
                    key={execution.id}
                    className="mb-2 border border-white bg-black/20 p-2"
                  >
                    <View className="flex-row items-center justify-between">
                      <Text className="text-[10px] font-bold text-white">
                        {formatLocalDateTime(
                          execution.finished_at ??
                            execution.started_at ??
                            execution.scheduled_for,
                          timeZone,
                        )}
                      </Text>
                      <Text
                        className={`text-[10px] font-bold ${executionStatusColor[execution.status]}`}
                      >
                        {execution.status.toUpperCase()}
                      </Text>
                    </View>
                    {execution.error_message ? (
                      <Text className="mt-1 text-[10px] font-bold text-red-400">
                        {execution.error_message}
                      </Text>
                    ) : null}
                    {execution.conversation_id ? (
                      <Button
                        className="mt-2 self-start"
                        label="Open Session"
                        size="xs"
                        variant="neo"
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
                    variant="neo"
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
