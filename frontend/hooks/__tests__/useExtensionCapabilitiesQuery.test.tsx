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
  append?: Partial<{
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported";
    routeMode: "unsupported" | "prompt_async" | "turn_steer" | "hybrid";
    requiresStreamIdentity: boolean;
  }>;
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
  append: {
    declared: true,
    consumedByHub: true,
    status: "supported" as const,
    routeMode: "prompt_async" as const,
    requiresStreamIdentity: false,
    ...overrides?.append,
  },
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
      sessionControl: createSessionControl({
        append: {
          routeMode: "hybrid",
        },
      }),
      invokeMetadata: createInvokeMetadata(),
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
    expect(result.current.sessionAppendStatus).toBe("supported");
    expect(result.current.sessionCommandStatus).toBe("supported");
    expect(result.current.sessionShellStatus).toBe("unsupported");
    expect(result.current.invokeMetadataStatus).toBe("unsupported");
    expect(result.current.sessionAppend?.routeMode).toBe("hybrid");
  });

  it("returns unsupported when model selection is unavailable", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: false,
      providerDiscovery: false,
      interruptRecovery: false,
      sessionPromptAsync: false,
      sessionControl: createSessionControl({
        append: {
          declared: true,
          consumedByHub: true,
          status: "unsupported",
          routeMode: "unsupported",
          requiresStreamIdentity: false,
        },
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
    expect(result.current.sessionAppendStatus).toBe("unsupported");
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
    expect(result.current.sessionAppendStatus).toBe("unknown");
    expect(result.current.sessionCommandStatus).toBe("unknown");
    expect(result.current.sessionShellStatus).toBe("unknown");
    expect(result.current.invokeMetadataStatus).toBe("unknown");
  });
});
