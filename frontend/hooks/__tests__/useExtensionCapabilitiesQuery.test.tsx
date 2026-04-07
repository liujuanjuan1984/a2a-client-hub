import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import { useExtensionCapabilitiesQuery } from "@/hooks/useExtensionCapabilitiesQuery";
import { getExtensionCapabilities } from "@/lib/api/a2aExtensions";
import { type RuntimeStatusContract } from "@/lib/api/chat-utils";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

jest.mock("@/lib/api/a2aExtensions", () => ({
  getExtensionCapabilities: jest.fn(),
}));

const mockedGetExtensionCapabilities =
  getExtensionCapabilities as jest.MockedFunction<
    typeof getExtensionCapabilities
  >;

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const createRuntimeStatus = (): RuntimeStatusContract => ({
  version: "v1",
  canonicalStates: [
    "working",
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
  ],
  terminalStates: [
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
  ],
  finalStates: ["completed", "failed", "cancelled"],
  interactiveStates: ["input-required", "auth-required"],
  failureStates: ["failed", "cancelled"],
  aliases: {
    input_required: "input-required",
    auth_required: "auth-required",
    canceled: "cancelled",
  },
  passthroughUnknown: true,
});

const createSessionControl = (overrides?: {
  promptAsync?: Partial<{
    declared: boolean;
    consumedByHub: boolean;
    availability: "always" | "conditional" | "unsupported";
  }>;
  command?: Partial<{
    declared: boolean;
    consumedByHub: boolean;
    availability: "always" | "conditional" | "unsupported";
  }>;
  shell?: Partial<{
    declared: boolean;
    consumedByHub: boolean;
    availability: "always" | "conditional" | "unsupported";
  }>;
}) => ({
  promptAsync: {
    declared: true,
    consumedByHub: true,
    availability: "always" as const,
    ...overrides?.promptAsync,
  },
  command: {
    declared: true,
    consumedByHub: true,
    availability: "always" as const,
    ...overrides?.command,
  },
  shell: {
    declared: false,
    consumedByHub: false,
    availability: "conditional" as const,
    ...overrides?.shell,
  },
});

const createInvokeMetadata = (overrides?: {
  declared?: boolean;
  consumedByHub?: boolean;
  status?: "supported" | "unsupported" | "invalid";
  metadataField?: string | null;
  appliesToMethods?: string[];
  fields?: {
    name: string;
    required: boolean;
    description?: string | null;
  }[];
}) => ({
  declared: false,
  consumedByHub: true,
  status: "unsupported" as const,
  metadataField: null,
  appliesToMethods: [],
  fields: [],
  ...overrides,
});

const createCodexDiscovery = (overrides?: {
  declared?: boolean;
  consumedByHub?: boolean;
  status?:
    | "unsupported"
    | "declared_not_consumed"
    | "partially_consumed"
    | "supported";
  methods?: Record<
    string,
    { declared: boolean; consumedByHub: boolean; method?: string | null }
  >;
}) => ({
  declared: false,
  consumedByHub: false,
  status: "unsupported" as const,
  methods: {},
  ...overrides,
});

describe("useExtensionCapabilitiesQuery", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("returns supported when model selection is available", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: true,
      providerDiscovery: true,
      interruptRecovery: true,
      sessionPromptAsync: true,
      sessionControl: createSessionControl(),
      invokeMetadata: createInvokeMetadata(),
      codexDiscovery: createCodexDiscovery({
        declared: true,
        consumedByHub: true,
        status: "supported",
        methods: {
          skillsList: {
            declared: true,
            consumedByHub: true,
            method: "codex.discovery.skills.list",
          },
          pluginsRead: {
            declared: true,
            consumedByHub: true,
            method: "codex.discovery.plugins.read",
          },
        },
      }),
      runtimeStatus: createRuntimeStatus(),
    });

    const { result } = renderHook(
      () =>
        useExtensionCapabilitiesQuery({
          agentId: "agent-1",
          source: "shared",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.modelSelectionStatus).toBe("supported");
    });
    expect(result.current.providerDiscoveryStatus).toBe("supported");
    expect(result.current.interruptRecoveryStatus).toBe("supported");
    expect(result.current.runtimeStatusContract?.version).toBe("v1");
    expect(result.current.sessionPromptAsyncStatus).toBe("supported");
    expect(result.current.sessionCommandStatus).toBe("supported");
    expect(result.current.sessionShellStatus).toBe("unsupported");
    expect(result.current.invokeMetadataStatus).toBe("unsupported");
    expect(result.current.codexDiscoveryStatus).toBe("supported");
    expect(result.current.canShowCodexDiscovery).toBe(true);
    expect(result.current.canReadCodexPlugins).toBe(true);
    expect(result.current.codexDiscoveryAvailableTabs).toEqual(["skills"]);
  });

  it("returns unsupported when model selection is unavailable", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: false,
      providerDiscovery: false,
      interruptRecovery: false,
      sessionPromptAsync: false,
      sessionControl: createSessionControl({
        promptAsync: { declared: false, availability: "unsupported" },
        command: {
          declared: false,
          consumedByHub: false,
          availability: "unsupported",
        },
        shell: {
          declared: false,
          consumedByHub: false,
          availability: "unsupported",
        },
      }),
      invokeMetadata: createInvokeMetadata(),
      codexDiscovery: createCodexDiscovery(),
      runtimeStatus: createRuntimeStatus(),
    });

    const { result } = renderHook(
      () =>
        useExtensionCapabilitiesQuery({
          agentId: "agent-1",
          source: "personal",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.modelSelectionStatus).toBe("unsupported");
    });
    expect(result.current.providerDiscoveryStatus).toBe("unsupported");
    expect(result.current.interruptRecoveryStatus).toBe("unsupported");
    expect(result.current.sessionPromptAsyncStatus).toBe("unsupported");
    expect(result.current.codexDiscoveryStatus).toBe("unsupported");
    expect(result.current.canShowCodexDiscovery).toBe(false);
  });

  it("distinguishes model selection from provider discovery", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: true,
      providerDiscovery: false,
      interruptRecovery: false,
      sessionPromptAsync: false,
      sessionControl: createSessionControl({
        promptAsync: { declared: false, availability: "unsupported" },
      }),
      invokeMetadata: createInvokeMetadata({
        declared: true,
        status: "supported",
        fields: [{ name: "project_id", required: true }],
      }),
      codexDiscovery: createCodexDiscovery({
        declared: true,
        consumedByHub: true,
        status: "partially_consumed",
        methods: {
          appsList: {
            declared: true,
            consumedByHub: true,
            method: "codex.discovery.apps.list",
          },
          watch: {
            declared: true,
            consumedByHub: false,
            method: "codex.discovery.watch",
          },
        },
      }),
      runtimeStatus: createRuntimeStatus(),
    });

    const { result } = renderHook(
      () =>
        useExtensionCapabilitiesQuery({
          agentId: "agent-1",
          source: "shared",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.modelSelectionStatus).toBe("supported");
    });
    expect(result.current.providerDiscoveryStatus).toBe("unsupported");
    expect(result.current.interruptRecoveryStatus).toBe("unsupported");
    expect(result.current.invokeMetadataStatus).toBe("supported");
    expect(result.current.codexDiscoveryStatus).toBe("partially_consumed");
    expect(result.current.codexDiscoveryAvailableTabs).toEqual(["apps"]);
  });

  it("returns unknown when capability lookup fails", async () => {
    mockedGetExtensionCapabilities.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(
      () =>
        useExtensionCapabilitiesQuery({
          agentId: "agent-1",
          source: "shared",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });

    expect(result.current.modelSelectionStatus).toBe("unknown");
    expect(result.current.providerDiscoveryStatus).toBe("unknown");
    expect(result.current.interruptRecoveryStatus).toBe("unknown");
    expect(result.current.sessionPromptAsyncStatus).toBe("unknown");
    expect(result.current.sessionCommandStatus).toBe("unknown");
    expect(result.current.sessionShellStatus).toBe("unknown");
    expect(result.current.invokeMetadataStatus).toBe("unknown");
    expect(result.current.codexDiscoveryStatus).toBe("unknown");
  });
});
