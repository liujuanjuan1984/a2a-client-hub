import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import {
  useCodexDiscoveryListQuery,
  useCodexPluginReadQuery,
} from "@/hooks/useCodexDiscoveryQuery";
import {
  type CodexDiscoveryAppsListResult,
  type CodexDiscoveryPluginsListResult,
  type CodexDiscoverySkillsListResult,
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
      items: [
        {
          cwd: "/workspace/project",
          skills: [
            {
              name: "Planning",
              path: "/workspace/project/.codex/skills/PLANNING/SKILL.md",
              description: "Summarize plans.",
              enabled: true,
              scope: "project",
              interface: null,
              codex: {},
            },
          ],
          errors: [],
          codex: {},
        },
      ],
    });
    mockedListCodexApps.mockResolvedValue({
      items: [
        {
          id: "app-1",
          name: "Workspace",
          description: "Manage files.",
          isAccessible: true,
          isEnabled: true,
          installUrl: null,
          mentionPath: "app://app-1",
          branding: null,
          labels: [],
          codex: {},
        },
      ],
      nextCursor: null,
    });
    mockedListCodexPlugins.mockResolvedValue({
      items: [
        {
          marketplaceName: "test",
          marketplacePath: "/workspace/.codex/plugins/marketplace.json",
          interface: null,
          plugins: [
            {
              name: "planner",
              description: "Coordinates work.",
              enabled: true,
              interface: null,
              mentionPath: "plugin://planner@test",
              codex: {},
            },
          ],
          codex: {},
        },
      ],
      featuredPluginIds: [],
      marketplaceLoadErrors: [],
      remoteSyncError: null,
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
      expect(
        (
          skillsResult.current.data as
            | CodexDiscoverySkillsListResult
            | undefined
        )?.items[0]?.cwd,
      ).toBe("/workspace/project");
    });
    await waitFor(() => {
      expect(
        (appsResult.current.data as CodexDiscoveryAppsListResult | undefined)
          ?.items[0]?.id,
      ).toBe("app-1");
    });
    await waitFor(() => {
      expect(
        (
          pluginsResult.current.data as
            | CodexDiscoveryPluginsListResult
            | undefined
        )?.items[0]?.marketplaceName,
      ).toBe("test");
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

  it("queries plugin details when marketplace path and plugin name are present", async () => {
    mockedReadCodexPlugin.mockResolvedValue({
      item: {
        name: "planner",
        marketplaceName: "test",
        marketplacePath: "/workspace/.codex/plugins/marketplace.json",
        mentionPath: "plugin://planner@test",
        summary: ["Use for planning"],
        skills: [],
        apps: [],
        mcpServers: [],
        interface: null,
        codex: {},
      },
    });

    const { result } = renderHook(
      () =>
        useCodexPluginReadQuery({
          agentId: "agent-1",
          source: "personal",
          marketplacePath: "/workspace/.codex/plugins/marketplace.json",
          pluginName: "planner",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.data?.item?.name).toBe("planner");
    });

    expect(mockedReadCodexPlugin).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      marketplacePath: "/workspace/.codex/plugins/marketplace.json",
      pluginName: "planner",
    });
  });
});
