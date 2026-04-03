import { useQuery } from "@tanstack/react-query";

import {
  type CodexExecCapability,
  getExtensionCapabilities,
  type CodexDiscoveryCapability,
  type CodexReviewCapability,
  type CodexDiscoveryStatus,
  type CodexThreadsCapability,
  type CodexTurnsCapability,
  type RequestExecutionOptionsCapability,
} from "@/lib/api/a2aExtensions";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentSource } from "@/store/agents";

export type GenericCapabilityStatus = "unknown" | "supported" | "unsupported";
type SessionControlMethodCapability = {
  declared: boolean;
  consumedByHub: boolean;
};
type InvokeMetadataCapability = {
  declared: boolean;
  consumedByHub: boolean;
  metadataField?: string | null;
  appliesToMethods: string[];
  fields: {
    name: string;
    required: boolean;
    description?: string | null;
  }[];
};
type DeclaredMethodCapability = {
  declared: boolean;
  consumedByHub: boolean;
};

const resolveSessionControlStatus = (
  method?: SessionControlMethodCapability | null,
): GenericCapabilityStatus => {
  if (!method) {
    return "unknown";
  }
  return method.declared && method.consumedByHub ? "supported" : "unsupported";
};

const isConsumedMethod = (method?: DeclaredMethodCapability | null) =>
  Boolean(method?.declared && method.consumedByHub);

export const useExtensionCapabilitiesQuery = ({
  agentId,
  source,
  enabled = true,
}: {
  agentId?: string | null;
  source?: AgentSource | null;
  enabled?: boolean;
}) => {
  const resolvedAgentId = agentId?.trim() || null;
  const resolvedSource = source ?? null;

  const query = useQuery({
    enabled: enabled && Boolean(resolvedAgentId && resolvedSource),
    queryKey:
      resolvedAgentId && resolvedSource
        ? queryKeys.agents.extensionCapabilities({
            agentId: resolvedAgentId,
            source: resolvedSource,
          })
        : (["agents", "extension-capabilities", "idle"] as const),
    queryFn: async () =>
      await getExtensionCapabilities({
        source: resolvedSource as AgentSource,
        agentId: resolvedAgentId as string,
      }),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const modelSelectionStatus: GenericCapabilityStatus =
    query.data?.modelSelection === true
      ? "supported"
      : query.data?.modelSelection === false
        ? "unsupported"
        : "unknown";
  const providerDiscoveryStatus: GenericCapabilityStatus =
    query.data?.providerDiscovery === true
      ? "supported"
      : query.data?.providerDiscovery === false
        ? "unsupported"
        : "unknown";
  const interruptRecoveryStatus: GenericCapabilityStatus =
    query.data?.interruptRecovery === true
      ? "supported"
      : query.data?.interruptRecovery === false
        ? "unsupported"
        : "unknown";
  const sessionPromptAsyncStatus: GenericCapabilityStatus =
    query.data?.sessionControl?.promptAsync != null
      ? resolveSessionControlStatus(query.data.sessionControl.promptAsync)
      : query.data?.sessionPromptAsync === true
        ? "supported"
        : query.data?.sessionPromptAsync === false
          ? "unsupported"
          : "unknown";
  const sessionCommandStatus: GenericCapabilityStatus =
    query.data?.sessionControl?.command != null
      ? resolveSessionControlStatus(query.data.sessionControl.command)
      : "unknown";
  const sessionShellStatus: GenericCapabilityStatus =
    query.data?.sessionControl?.shell != null
      ? resolveSessionControlStatus(query.data.sessionControl.shell)
      : "unknown";
  const invokeMetadataStatus: GenericCapabilityStatus =
    query.data?.invokeMetadata != null
      ? query.data.invokeMetadata.declared &&
        query.data.invokeMetadata.consumedByHub
        ? "supported"
        : "unsupported"
      : "unknown";
  const codexDiscoveryStatus: CodexDiscoveryStatus =
    query.data?.codexDiscovery?.status ?? "unknown";
  const codexDiscovery =
    (query.data?.codexDiscovery as
      | CodexDiscoveryCapability
      | null
      | undefined) ?? null;
  const codexDiscoveryAvailableTabs = [
    isConsumedMethod(codexDiscovery?.methods.skillsList) ? "skills" : null,
    isConsumedMethod(codexDiscovery?.methods.appsList) ? "apps" : null,
    isConsumedMethod(codexDiscovery?.methods.pluginsList) ? "plugins" : null,
  ].filter((item): item is "skills" | "apps" | "plugins" => Boolean(item));
  const canReadCodexPlugins = isConsumedMethod(
    codexDiscovery?.methods.pluginsRead,
  );
  const codexThreads =
    (query.data?.codexThreads as CodexThreadsCapability | null | undefined) ??
    null;
  const codexTurns =
    (query.data?.codexTurns as CodexTurnsCapability | null | undefined) ?? null;
  const codexReview =
    (query.data?.codexReview as CodexReviewCapability | null | undefined) ??
    null;
  const codexExec =
    (query.data?.codexExec as CodexExecCapability | null | undefined) ?? null;
  const requestExecutionOptions =
    (query.data?.requestExecutionOptions as
      | RequestExecutionOptionsCapability
      | null
      | undefined) ?? null;

  return {
    ...query,
    runtimeStatusContract: query.data?.runtimeStatus ?? null,
    modelSelectionStatus,
    providerDiscoveryStatus,
    interruptRecoveryStatus,
    sessionPromptAsyncStatus,
    sessionCommandStatus,
    sessionShellStatus,
    invokeMetadataStatus,
    codexDiscoveryStatus,
    sessionControl: query.data?.sessionControl ?? null,
    invokeMetadata:
      (query.data?.invokeMetadata as InvokeMetadataCapability) ?? null,
    codexDiscovery,
    codexThreads,
    codexTurns,
    codexReview,
    codexExec,
    requestExecutionOptions,
    codexDiscoveryAvailableTabs,
    canShowCodexDiscovery: codexDiscoveryAvailableTabs.length > 0,
    canReadCodexPlugins,
    canShowModelPicker: modelSelectionStatus !== "unsupported",
  };
};
