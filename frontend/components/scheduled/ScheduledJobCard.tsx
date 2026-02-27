import { useRouter } from "expo-router";
import { useState } from "react";
import { Switch, Text, View } from "react-native";

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

const getCardTone = (job: ScheduledJob, isReallyRunning: boolean) => {
  if (!job.enabled) {
    return {
      container: "opacity-80",
      title: "text-slate-500",
      text: "text-slate-600",
      prompt: "text-slate-600",
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
  const isReallyRunning =
    job.last_run_status === "running" ||
    executions.some((e) => e.status === "running");
  const tone = getCardTone(job, isReallyRunning);
  const intervalTimePoint =
    job.cycle_type === "interval" &&
    typeof (job.time_point as IntervalTimePoint)?.minutes === "number"
      ? (job.time_point as IntervalTimePoint)
      : null;
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [markingFailed, setMarkingFailed] = useState(false);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const canMarkFailed = isReallyRunning;

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
      className={`mb-4 rounded-2xl overflow-hidden bg-surface shadow-sm ${tone.container}`}
    >
      <View className="p-5">
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-[11px] font-semibold uppercase tracking-widest text-neo-green">
            {agentName}
          </Text>
          <View className="bg-black/20 rounded px-1.5 py-0.5">
            <Text className={`text-[9px] font-bold ${tone.text}`}>
              {tone.statusText}
            </Text>
          </View>
        </View>

        <View className="flex-row items-start justify-between">
          <View className="flex-1 pr-3">
            <Text className={`text-sm font-bold ${tone.title}`}>
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

        {promptExpanded && (
          <View className="mt-4 pt-4 border-t border-white/5">
            <Text className={`text-sm leading-6 ${tone.prompt}`}>
              {job.prompt}
            </Text>
          </View>
        )}
      </View>

      <View className="flex-row items-center justify-between gap-3 bg-black/30 px-5 py-3">
        <View className="flex-row items-center gap-2">
          <Button
            label="Edit"
            size="xs"
            variant="secondary"
            iconLeft="create-outline"
            onPress={onEdit}
          />
          <Button
            label={promptExpanded ? "Less" : "Info"}
            size="xs"
            variant={promptExpanded ? "primary" : "secondary"}
            iconLeft={
              promptExpanded ? "chevron-up" : "information-circle-outline"
            }
            onPress={() => setPromptExpanded(!promptExpanded)}
          />
          <Button
            label={executionsOpen ? "Hide" : "History"}
            size="xs"
            variant={executionsOpen ? "primary" : "secondary"}
            iconLeft={executionsOpen ? "time" : "time-outline"}
            onPress={onToggleExecutions}
          />
        </View>

        {canMarkFailed ? (
          <Button
            label="Stop"
            size="xs"
            variant="danger"
            className="bg-red-500/40"
            loading={markingFailed}
            disabled={!onMarkFailed}
            onPress={handleMarkFailed}
          />
        ) : null}
      </View>

      {executionsOpen ? (
        <View className="bg-black/10 px-5 pb-5 pt-1">
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
                {executions.map((execution) => (
                  <View
                    key={execution.id}
                    className="mb-2 rounded-xl bg-black/20 p-3"
                  >
                    <View className="flex-row items-center justify-between">
                      <Text className="text-[10px] font-medium text-slate-500">
                        {formatLocalDateTime(
                          execution.finished_at ??
                            execution.started_at ??
                            execution.scheduled_for,
                          timeZone,
                        )}
                      </Text>
                      <View className="rounded px-1 py-0.5 bg-black/20">
                        <Text
                          className={`text-[9px] font-bold ${executionStatusColor[execution.status]}`}
                        >
                          {execution.status.toUpperCase()}
                        </Text>
                      </View>
                    </View>
                    {execution.error_message ? (
                      <Text className="mt-2 text-[11px] font-normal text-red-400/80">
                        {execution.error_message}
                      </Text>
                    ) : null}
                    {execution.conversation_id ? (
                      <Button
                        className="mt-3 self-start"
                        label="Open Session"
                        size="xs"
                        variant="secondary"
                        onPress={() => openExecutionSession(execution)}
                      />
                    ) : null}
                  </View>
                ))}

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
