import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { ScheduledJobCard } from "@/components/scheduled/ScheduledJobCard";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useScheduledJobExecutionsQuery } from "@/hooks/useScheduledJobExecutionsQuery";
import { useScheduledJobs } from "@/hooks/useScheduledJobs";
import { useScheduledJobsQuery } from "@/hooks/useScheduledJobsQuery";
import { resolveUserTimeZone } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { buildScheduledJobEditHref, scheduledJobNewHref } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useSessionStore } from "@/store/session";

export function ScheduledJobsScreen() {
  const router = useRouter();
  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const { markJobFailed, toggleJobStatus } = useScheduledJobs();
  const userTimeZone = useSessionStore((state) => state.user?.timezone);
  const localTimeZone = resolveUserTimeZone();
  const scheduleTimeZone = userTimeZone?.trim() || localTimeZone;
  const hasTimeZoneMismatch =
    userTimeZone?.trim() && userTimeZone?.trim() !== localTimeZone;

  const [expandedExecutionsTaskId, setExpandedExecutionsTaskId] = useState<
    string | null
  >(null);

  const agentOptions = useMemo(
    () => agents.map((agent) => ({ id: agent.id, name: agent.name })),
    [agents],
  );

  const {
    items: jobs,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    loadFirstPage,
    loadMore,
  } = useScheduledJobsQuery({ enabled: true });

  const sortedJobs = useMemo(() => {
    return [...jobs].sort((a, b) => {
      if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;

      if (a.enabled && b.enabled) {
        const ar = a.last_run_status === "running";
        const br = b.last_run_status === "running";
        if (ar !== br) return ar ? -1 : 1;

        const at = a.next_run_at_utc
          ? new Date(a.next_run_at_utc).getTime()
          : Number.POSITIVE_INFINITY;
        const bt = b.next_run_at_utc
          ? new Date(b.next_run_at_utc).getTime()
          : Number.POSITIVE_INFINITY;
        if (at !== bt) return at - bt;
      }

      return String(a.id).localeCompare(String(b.id));
    });
  }, [jobs]);

  const executionsQuery = useScheduledJobExecutionsQuery({
    taskId: expandedExecutionsTaskId ?? undefined,
    enabled: Boolean(expandedExecutionsTaskId),
  });

  const onRefresh = async () => {
    await loadFirstPage("refreshing");
  };

  const toggleExecutionsPanel = (taskId: string) => {
    setExpandedExecutionsTaskId((current) =>
      current === taskId ? null : taskId,
    );
  };

  return (
    <ScreenContainer>
      <PageHeader
        title="Scheduled Jobs"
        subtitle="Configure recurring prompts and inspect execution history."
        rightElement={
          <View className="flex-row gap-2">
            <IconButton
              accessibilityLabel="Create job"
              icon="add"
              size="sm"
              onPress={() => {
                blurActiveElement();
                router.push(scheduledJobNewHref);
              }}
            />
          </View>
        }
      />

      {hasTimeZoneMismatch && (
        <View className="mx-6 mb-2 flex-row items-center gap-2 rounded-xl bg-orange-500/10 p-3">
          <Ionicons name="alert-circle-outline" size={14} color="#FB923C" />
          <Text className="text-[11px] font-medium text-orange-400">
            Note: Displaying times in {scheduleTimeZone} (Local: {localTimeZone}
            )
          </Text>
        </View>
      )}

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#FFFFFF"
            colors={["#FFFFFF"]}
          />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-gray-400">Loading jobs...</Text>
          </View>
        ) : sortedJobs.length === 0 ? (
          <View className="mt-8 rounded-2xl bg-surface p-8 items-center shadow-sm">
            <View className="h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 border border-primary/20 mb-4">
              <Ionicons name="time-outline" size={32} color="#FACC15" />
            </View>
            <Text className="text-base font-bold text-white">
              No scheduled jobs
            </Text>
            <Text className="mt-2 text-center text-[11px] font-medium text-slate-400">
              Create your first recurring task to automate prompts.
            </Text>
            <Button
              className="mt-6"
              label="Create a job"
              size="sm"
              iconRight="chevron-forward"
              onPress={() => {
                blurActiveElement();
                router.push(scheduledJobNewHref);
              }}
            />
          </View>
        ) : (
          sortedJobs.map((job) => {
            const executionsOpen = expandedExecutionsTaskId === job.id;
            return (
              <ScheduledJobCard
                key={job.id}
                job={job}
                timeZone={job.schedule_timezone || scheduleTimeZone}
                agentName={
                  agentOptions.find((agent) => agent.id === job.agent_id)
                    ?.name ?? job.agent_id
                }
                executions={executionsOpen ? executionsQuery.items : []}
                executionsOpen={executionsOpen}
                executionsLoading={
                  executionsOpen ? executionsQuery.loading : false
                }
                executionsHasMore={
                  executionsOpen ? executionsQuery.hasMore : false
                }
                executionsLoadingMore={
                  executionsOpen ? executionsQuery.loadingMore : false
                }
                onToggleEnabled={async () => {
                  try {
                    await toggleJobStatus(job);
                  } catch (error) {
                    const message =
                      error instanceof Error ? error.message : "Update failed.";
                    toast.error("Update failed", message);
                  }
                }}
                onEdit={() => {
                  blurActiveElement();
                  router.push(buildScheduledJobEditHref(job.id));
                }}
                onMarkFailed={async () => {
                  try {
                    await markJobFailed(job);
                    toast.success(
                      "Job updated",
                      "Marked running task as failed.",
                    );
                  } catch (error) {
                    const message =
                      error instanceof Error ? error.message : "Update failed.";
                    toast.error("Update failed", message);
                  }
                }}
                onToggleExecutions={() => toggleExecutionsPanel(job.id)}
                onLoadMoreExecutions={
                  executionsOpen
                    ? async () => {
                        await executionsQuery.loadMore();
                      }
                    : undefined
                }
              />
            );
          })
        )}

        {hasMore ? (
          <Button
            className="mt-2 self-center"
            label={loadingMore ? "Loading..." : "Load more"}
            size="sm"
            variant="secondary"
            loading={loadingMore}
            onPress={() => loadMore()}
          />
        ) : null}
      </ScrollView>
    </ScreenContainer>
  );
}
