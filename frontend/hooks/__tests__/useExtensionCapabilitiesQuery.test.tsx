import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import { useExtensionCapabilitiesQuery } from "@/hooks/useExtensionCapabilitiesQuery";
import { getExtensionCapabilities } from "@/lib/api/a2aExtensions";
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
    mockedGetExtensionCapabilities.mockResolvedValue({ modelSelection: true });

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
  });

  it("returns unsupported when model selection is unavailable", async () => {
    mockedGetExtensionCapabilities.mockResolvedValue({ modelSelection: false });

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
  });
});
