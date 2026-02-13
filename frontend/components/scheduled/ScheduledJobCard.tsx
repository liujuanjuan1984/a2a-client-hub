import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Switch, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import {
  type ScheduledJob,
  type ScheduledJobExecution,
} from "@/lib/api/scheduledJobs";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { buildScheduledSessionId } from "@/lib/sessionIds";
import { toast } from "@/lib/toast";

const executionStatusColor: Record<ScheduledJobExecution["status"], string> = {
  running: "text-blue-300",
  success: "text-emerald-300",
  failed: "text-red-300",
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
  onToggleExecutions,
  onLoadMoreExecutions,
}: ScheduledJobCardProps) {
  const router = useRouter();
  const enabledLabel = job.enabled ? "Enabled" : "Disabled";
  const historyLabel = executionsOpen ? "Hide" : "History";
  const historyIcon = executionsOpen ? "time" : "time-outline";
  const [togglingEnabled, setTogglingEnabled] = useState(false);

  const openExecutionSession = (execution: ScheduledJobExecution) => {
    if (!execution.session_id) return;
    const agentId = job.agent_id;
    if (!agentId) {
      toast.error(
        "Open session failed",
        "Missing agent id for this execution.",
      );
      return;
    }

    blurActiveElement();
    router.push(
      buildChatRoute(agentId, buildScheduledSessionId(execution.session_id)),
    );
  };

  return (
    <View className="mb-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30">
      <View className="p-4">
        <View className="flex-row items-start justify-between">
          <View className="flex-1 pr-3">
            <Text className="text-base font-semibold text-white">
              {job.name}
            </Text>
            <Text className="mt-1 text-xs text-slate-400">
              Agent: {agentName}
            </Text>
            <Text className="mt-1 text-xs text-slate-400">
              {job.cycle_type}
            </Text>
            <Text className="mt-1 text-xs text-slate-400">
              Next: {formatLocalDateTime(job.next_run_at)}
            </Text>
            <Text className="mt-1 text-xs text-slate-400">
              Last: {formatLocalDateTime(job.last_run_at)} (
              {job.last_run_status ?? "-"})
            </Text>
          </View>
          <View className="flex-row items-center gap-2">
            <Text className="text-xs font-semibold text-slate-200">
              {enabledLabel}
            </Text>
            <Switch
              value={job.enabled}
              disabled={togglingEnabled}
              trackColor={{ false: "#334155", true: "#5c6afb" }}
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
              accessibilityLabel={`Job enabled: ${enabledLabel}`}
            />
          </View>
        </View>

        <Text className="mt-3 text-xs text-slate-300" numberOfLines={2}>
          {job.prompt}
        </Text>
      </View>

      <View className="flex-row items-center justify-start gap-3 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
        <Pressable
          className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
          onPress={onEdit}
          accessibilityRole="button"
          accessibilityLabel="Edit"
          accessibilityHint="Edit this scheduled job"
        >
          <Ionicons name="create-outline" size={14} color="#94a3b8" />
          <Text className="text-xs font-medium text-slate-400">Edit</Text>
        </Pressable>

        <Pressable
          className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
          onPress={onToggleExecutions}
          accessibilityRole="button"
          accessibilityLabel={historyLabel}
          accessibilityHint={`${historyLabel} execution history`}
        >
          <Ionicons name={historyIcon} size={14} color="#94a3b8" />
          <Text className="text-xs font-medium text-slate-400">
            {historyLabel}
          </Text>
        </Pressable>
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
                    {execution.session_id ? (
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
