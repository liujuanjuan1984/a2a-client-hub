import { useFocusEffect } from "@react-navigation/native";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
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
import { blurActiveElement } from "@/lib/focus";
import { buildScheduledJobEditHref, scheduledJobNewHref } from "@/lib/routes";
import { toast } from "@/lib/toast";

export function ScheduledJobsScreen() {
  const router = useRouter();
  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const { markJobFailed, toggleJobStatus } = useScheduledJobs();

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

  const sortedJobs = useMemo(() => {
    return [...jobs].sort((a, b) => {
      if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;

      if (a.enabled && b.enabled) {
        const ar = a.last_run_status === "running";
        const br = b.last_run_status === "running";
        if (ar !== br) return ar ? -1 : 1;

        const at = a.next_run_at
          ? new Date(a.next_run_at).getTime()
          : Number.POSITIVE_INFINITY;
        const bt = b.next_run_at
          ? new Date(b.next_run_at).getTime()
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

  const hasLoadedRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      const mode = hasLoadedRef.current ? "refreshing" : "loading";
      loadFirstPage(mode)
        .then((succeeded) => {
          if (succeeded) {
            hasLoadedRef.current = true;
          }
        })
        .catch((err) => {
          console.error("Scheduled jobs load error:", err);
        });
    }, [loadFirstPage]),
  );

  const onRefresh = async () => {
    const succeeded = await loadFirstPage("refreshing");
    if (succeeded) {
      hasLoadedRef.current = true;
    }
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

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-muted">Loading jobs...</Text>
          </View>
        ) : sortedJobs.length === 0 ? (
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
          sortedJobs.map((job) => {
            const executionsOpen = expandedExecutionsTaskId === job.id;
            return (
              <ScheduledJobCard
                key={job.id}
                job={job}
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
                    const succeeded = await loadFirstPage("refreshing");
                    if (succeeded) {
                      hasLoadedRef.current = true;
                    }
                    if (expandedExecutionsTaskId === job.id) {
                      await executionsQuery.loadFirstPage("refreshing");
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
                onMarkFailed={async () => {
                  try {
                    await markJobFailed(job);
                    const succeeded = await loadFirstPage("refreshing");
                    if (succeeded) {
                      hasLoadedRef.current = true;
                    }
                    if (expandedExecutionsTaskId === job.id) {
                      await executionsQuery.loadFirstPage("refreshing");
                    }
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
