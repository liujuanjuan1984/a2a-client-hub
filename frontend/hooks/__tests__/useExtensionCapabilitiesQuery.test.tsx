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
      sessionPromptAsync: true,
      sessionControl: createSessionControl(),
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
    expect(result.current.runtimeStatusContract?.version).toBe("v1");
    expect(result.current.sessionPromptAsyncStatus).toBe("supported");
    expect(result.current.sessionCommandStatus).toBe("supported");
    expect(result.current.sessionShellStatus).toBe("unsupported");
  });

  it("returns unsupported when model selection is unavailable", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: false,
      providerDiscovery: false,
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
    expect(result.current.sessionPromptAsyncStatus).toBe("unsupported");
  });

  it("distinguishes model selection from provider discovery", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({
      modelSelection: true,
      providerDiscovery: false,
      sessionPromptAsync: false,
      sessionControl: createSessionControl({
        promptAsync: { declared: false, availability: "unsupported" },
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
    expect(result.current.sessionPromptAsyncStatus).toBe("unknown");
    expect(result.current.sessionCommandStatus).toBe("unknown");
    expect(result.current.sessionShellStatus).toBe("unknown");
  });
});
