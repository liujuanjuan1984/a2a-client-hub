import { useFocusEffect } from "@react-navigation/native";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { ScheduledJobCard } from "@/components/scheduled/ScheduledJobCard";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useScheduledJobs } from "@/hooks/useScheduledJobs";
import { useScheduledJobsQuery } from "@/hooks/useScheduledJobsQuery";
import { blurActiveElement } from "@/lib/focus";
import { buildScheduledJobEditHref, scheduledJobNewHref } from "@/lib/routes";
import { toast } from "@/lib/toast";

export function ScheduledJobsScreen() {
  const router = useRouter();
  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const {
    executionsByTaskId,
    executionsNextPageByTaskId,
    loadingExecutionsTaskId,
    loadingMoreExecutionsTaskId,
    loadExecutions,
    loadMoreExecutions,
    toggleJobStatus,
  } = useScheduledJobs();

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
  } = useScheduledJobsQuery({ enabled: false });

  const hasLoadedRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      const mode = hasLoadedRef.current ? "refreshing" : "loading";
      loadFirstPage(mode).then((succeeded) => {
        if (succeeded) {
          hasLoadedRef.current = true;
        }
      });
    }, [loadFirstPage]),
  );

  const onRefresh = async () => {
    const succeeded = await loadFirstPage("refreshing");
    if (succeeded) {
      hasLoadedRef.current = true;
    }
  };

  const toggleExecutionsPanel = async (taskId: string) => {
    if (expandedExecutionsTaskId === taskId) {
      setExpandedExecutionsTaskId(null);
      return;
    }
    setExpandedExecutionsTaskId(taskId);
    if (!executionsByTaskId[taskId]) {
      try {
        await loadExecutions(taskId);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Load failed.";
        toast.error("Load executions failed", message);
      }
    }
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

      <ScrollView
        className="mt-2"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-muted">Loading jobs...</Text>
          </View>
        ) : jobs.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No scheduled jobs
            </Text>
            <Text className="mt-2 text-sm text-muted">
              Create your first recurring task to automate prompts.
            </Text>
            <Button
              className="mt-4 self-start"
              label="Create job"
              size="sm"
              iconRight="chevron-forward"
              onPress={() => {
                blurActiveElement();
                router.push(scheduledJobNewHref);
              }}
            />
          </View>
        ) : (
          jobs.map((job) => (
            <ScheduledJobCard
              key={job.id}
              job={job}
              agentName={
                agentOptions.find((agent) => agent.id === job.agent_id)?.name ??
                job.agent_id
              }
              executions={executionsByTaskId[job.id] ?? []}
              executionsOpen={expandedExecutionsTaskId === job.id}
              executionsLoading={loadingExecutionsTaskId === job.id}
              executionsHasMore={
                typeof executionsNextPageByTaskId[job.id] === "number"
              }
              executionsLoadingMore={loadingMoreExecutionsTaskId === job.id}
              onToggleEnabled={async () => {
                try {
                  await toggleJobStatus(job);
                  const succeeded = await loadFirstPage("refreshing");
                  if (succeeded) {
                    hasLoadedRef.current = true;
                  }
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
              onToggleExecutions={() => toggleExecutionsPanel(job.id)}
              onLoadMoreExecutions={async () => {
                try {
                  await loadMoreExecutions(job.id);
                } catch (error) {
                  const message =
                    error instanceof Error ? error.message : "Load failed.";
                  toast.error("Load executions failed", message);
                }
              }}
            />
          ))
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
