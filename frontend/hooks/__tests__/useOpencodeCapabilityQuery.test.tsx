import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import { useOpencodeCapabilityQuery } from "@/hooks/useOpencodeCapabilityQuery";
import { getOpencodeDiscoveryCapability } from "@/lib/api/a2aExtensions";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

jest.mock("@/lib/api/a2aExtensions", () => ({
  getOpencodeDiscoveryCapability: jest.fn(),
}));

const mockedGetOpencodeDiscoveryCapability =
  getOpencodeDiscoveryCapability as jest.MockedFunction<
    typeof getOpencodeDiscoveryCapability
  >;

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useOpencodeCapabilityQuery", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("returns supported when capability endpoint reports support", async () => {
    mockedGetOpencodeDiscoveryCapability.mockResolvedValue({ supported: true });

    const { result } = renderHook(
      () =>
        useOpencodeCapabilityQuery({
          agentId: "agent-1",
          source: "shared",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.capabilityStatus).toBe("supported");
    });

    expect(mockedGetOpencodeDiscoveryCapability).toHaveBeenCalledWith({
      agentId: "agent-1",
      source: "shared",
    });
    expect(result.current.canShowModelPicker).toBe(true);
  });

  it("returns unsupported when capability endpoint reports no support", async () => {
    mockedGetOpencodeDiscoveryCapability.mockResolvedValue({
      supported: false,
    });

    const { result } = renderHook(
      () =>
        useOpencodeCapabilityQuery({
          agentId: "agent-1",
          source: "personal",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.capabilityStatus).toBe("unsupported");
    });

    expect(result.current.canShowModelPicker).toBe(false);
  });

  it("returns unknown when capability lookup fails", async () => {
    mockedGetOpencodeDiscoveryCapability.mockRejectedValue(
      new Error("network down"),
    );

    const { result } = renderHook(
      () =>
        useOpencodeCapabilityQuery({
          agentId: "agent-1",
          source: "shared",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });

    expect(result.current.capabilityStatus).toBe("unknown");
    expect(result.current.canShowModelPicker).toBe(true);
  });

  it("does not call the endpoint before agent identity is ready", () => {
    const { result } = renderHook(
      () =>
        useOpencodeCapabilityQuery({
          agentId: null,
          source: null,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    expect(mockedGetOpencodeDiscoveryCapability).not.toHaveBeenCalled();
    expect(result.current.capabilityStatus).toBe("unknown");
    expect(result.current.canShowModelPicker).toBe(true);
  });
});
