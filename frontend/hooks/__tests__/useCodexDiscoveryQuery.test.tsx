import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import {
  useCodexDiscoveryListQuery,
  useCodexPluginReadQuery,
} from "@/hooks/useCodexDiscoveryQuery";
import {
  listCodexApps,
  listCodexPlugins,
  listCodexSkills,
  readCodexPlugin,
} from "@/lib/api/a2aExtensions";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

jest.mock("@/lib/api/a2aExtensions", () => ({
  listCodexApps: jest.fn(),
  listCodexPlugins: jest.fn(),
  listCodexSkills: jest.fn(),
  readCodexPlugin: jest.fn(),
}));

const mockedListCodexSkills = jest.mocked(listCodexSkills);
const mockedListCodexApps = jest.mocked(listCodexApps);
const mockedListCodexPlugins = jest.mocked(listCodexPlugins);
const mockedReadCodexPlugin = jest.mocked(readCodexPlugin);

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useCodexDiscoveryQuery", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("queries codex discovery lists by kind", async () => {
    mockedListCodexSkills.mockResolvedValue({
      items: [{ id: "skill-1", kind: "skill", tags: [], metadata: {} }],
      nextCursor: null,
    });
    mockedListCodexApps.mockResolvedValue({
      items: [{ id: "app-1", kind: "app", tags: [], metadata: {} }],
      nextCursor: null,
    });
    mockedListCodexPlugins.mockResolvedValue({
      items: [{ id: "plugin-1", kind: "plugin", tags: [], metadata: {} }],
      nextCursor: null,
    });

    const { result: skillsResult } = renderHook(
      () =>
        useCodexDiscoveryListQuery({
          agentId: "agent-1",
          source: "shared",
          kind: "skills",
        }),
      { wrapper: createWrapper(queryClient) },
    );
    const { result: appsResult } = renderHook(
      () =>
        useCodexDiscoveryListQuery({
          agentId: "agent-1",
          source: "shared",
          kind: "apps",
        }),
      { wrapper: createWrapper(queryClient) },
    );
    const { result: pluginsResult } = renderHook(
      () =>
        useCodexDiscoveryListQuery({
          agentId: "agent-1",
          source: "shared",
          kind: "plugins",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(skillsResult.current.data?.items[0]?.id).toBe("skill-1");
    });
    await waitFor(() => {
      expect(appsResult.current.data?.items[0]?.id).toBe("app-1");
    });
    await waitFor(() => {
      expect(pluginsResult.current.data?.items[0]?.id).toBe("plugin-1");
    });

    expect(mockedListCodexSkills).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
    });
    expect(mockedListCodexApps).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
    });
    expect(mockedListCodexPlugins).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
    });
  });

  it("queries plugin details when a plugin id is present", async () => {
    mockedReadCodexPlugin.mockResolvedValue({
      plugin: {
        id: "planner",
        kind: "plugin",
        tags: [],
        metadata: {},
        content: { readme: "Use for planning" },
      },
    });

    const { result } = renderHook(
      () =>
        useCodexPluginReadQuery({
          agentId: "agent-1",
          source: "personal",
          pluginId: "planner",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.data?.plugin?.id).toBe("planner");
    });

    expect(mockedReadCodexPlugin).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      pluginId: "planner",
    });
  });
});
