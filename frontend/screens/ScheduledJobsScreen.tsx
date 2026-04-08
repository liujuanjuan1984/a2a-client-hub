import Ionicons from "@expo/vector-icons/Ionicons";
import { useRouter } from "expo-router";
import { useMemo, useState, useCallback } from "react";
import { RefreshControl, FlatList, Text, View } from "react-native";

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
  const { markJobFailed, toggleJobStatus, removeJob } = useScheduledJobs();
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

  const renderJobItem = useCallback(
    ({ item: job }: { item: any }) => {
      const executionsOpen = expandedExecutionsTaskId === job.id;
      return (
        <ScheduledJobCard
          key={job.id}
          job={job}
          timeZone={job.schedule_timezone || scheduleTimeZone}
          agentName={
            agentOptions.find((agent) => agent.id === job.agent_id)?.name ??
            job.agent_id
          }
          executions={executionsOpen ? executionsQuery.items : []}
          executionsOpen={executionsOpen}
          executionsLoading={executionsOpen ? executionsQuery.loading : false}
          executionsHasMore={executionsOpen ? executionsQuery.hasMore : false}
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
          onDelete={async () => {
            try {
              await removeJob(job);
              toast.success(
                "Job deleted",
                "The scheduled task has been removed.",
              );
            } catch (error) {
              const message =
                error instanceof Error ? error.message : "Delete failed.";
              toast.error("Delete failed", message);
            }
          }}
          onMarkFailed={async () => {
            try {
              await markJobFailed(job);
              toast.success(
                "Run stopped",
                job.status_summary?.manual_intervention_recommended
                  ? "Marked the stalled run as failed."
                  : "Marked the running task as failed.",
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
    },
    [
      expandedExecutionsTaskId,
      scheduleTimeZone,
      agentOptions,
      executionsQuery,
      toggleJobStatus,
      router,
      removeJob,
      markJobFailed,
    ],
  );

  return (
    <ScreenContainer className="flex-1 bg-background px-5 sm:px-6">
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

      <FlatList
        data={jobs}
        renderItem={renderJobItem}
        keyExtractor={(item) => item.id}
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 18 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#FFFFFF"
            colors={["#FFFFFF"]}
          />
        }
        ListHeaderComponent={
          hasTimeZoneMismatch ? (
            <View className="mb-4 flex-row items-center gap-2 rounded-xl bg-orange-500/10 p-3 mx-1">
              <Ionicons name="alert-circle-outline" size={14} color="#FB923C" />
              <Text className="text-[11px] font-medium text-orange-400">
                Note: Displaying times in {scheduleTimeZone} (Local:{" "}
                {localTimeZone})
              </Text>
            </View>
          ) : null
        }
        ListEmptyComponent={
          loading ? (
            <View className="mt-8 items-center">
              <Text className="text-sm text-gray-400">Loading jobs...</Text>
            </View>
          ) : (
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
          )
        }
        onEndReached={() => {
          if (hasMore && !loadingMore) {
            loadMore();
          }
        }}
        onEndReachedThreshold={0.5}
        ListFooterComponent={
          hasMore ? (
            <View className="py-4 items-center">
              <Button
                label={loadingMore ? "Loading..." : "Load more"}
                size="sm"
                variant="secondary"
                loading={loadingMore}
                onPress={() => loadMore()}
              />
            </View>
          ) : null
        }
      />
    </ScreenContainer>
  );
}
