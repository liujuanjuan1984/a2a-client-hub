import type React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { CodexDiscoveryModal } from "../CodexDiscoveryModal";

import {
  useCodexDiscoveryListQuery,
  useCodexPluginReadQuery,
} from "@/hooks/useCodexDiscoveryQuery";

jest.mock("react-native/Libraries/Modal/Modal", () => {
  return {
    __esModule: true,
    default: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
    Modal: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
  };
});

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("@/lib/api/a2aExtensions", () => {
  class MockA2AExtensionCallError extends Error {
    errorCode: string | null;

    constructor(message: string, options?: { errorCode?: string | null }) {
      super(message);
      this.name = "A2AExtensionCallError";
      this.errorCode = options?.errorCode ?? null;
    }
  }

  return {
    A2AExtensionCallError: MockA2AExtensionCallError,
    toCodexDiscoveryEntries: (kind: string, result: { items?: unknown[] }) => {
      if (kind !== "plugins") {
        return [];
      }
      return (result.items ?? []).flatMap((marketplace) => {
        const item = marketplace as {
          marketplacePath?: string;
          plugins?: {
            name?: string;
            description?: string | null;
            mentionPath?: string | null;
          }[];
        };
        return (item.plugins ?? []).map((plugin) => ({
          id: plugin.name ?? "plugin",
          kind: "plugin",
          title: plugin.name ?? "plugin",
          description: plugin.description ?? null,
          subtitle: plugin.mentionPath ?? null,
          badge: null,
          pluginRef:
            item.marketplacePath && plugin.name
              ? {
                  marketplacePath: item.marketplacePath,
                  pluginName: plugin.name,
                }
              : null,
        }));
      });
    },
  };
});

jest.mock("@/hooks/useCodexDiscoveryQuery", () => ({
  useCodexDiscoveryListQuery: jest.fn(),
  useCodexPluginReadQuery: jest.fn(),
}));

const mockedUseCodexDiscoveryListQuery = jest.mocked(
  useCodexDiscoveryListQuery,
);
const mockedUseCodexPluginReadQuery = jest.mocked(useCodexPluginReadQuery);

type CodexDiscoveryModalProps = React.ComponentProps<
  typeof CodexDiscoveryModal
>;

const baseProps: CodexDiscoveryModalProps = {
  visible: true,
  onClose: jest.fn(),
  agentId: "agent-1",
  source: "shared" as const,
  codexDiscoveryStatus: "supported",
  codexDiscovery: {
    declared: true,
    consumedByHub: true,
    status: "supported",
    methods: {
      skillsList: {
        declared: true,
        consumedByHub: true,
        method: "codex.discovery.skills.list",
      },
      pluginsList: {
        declared: true,
        consumedByHub: true,
        method: "codex.discovery.plugins.list",
      },
      pluginsRead: {
        declared: true,
        consumedByHub: true,
        method: "codex.discovery.plugins.read",
      },
    },
  },
  availableTabs: ["plugins"],
  canReadPlugins: true,
};

const createQueryResult = (overrides?: Record<string, unknown>) => ({
  data: undefined,
  error: null,
  isError: false,
  isLoading: false,
  ...overrides,
});

const renderModal = async (overrides?: Partial<CodexDiscoveryModalProps>) => {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CodexDiscoveryModal {...baseProps} {...overrides} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
  return tree;
};

describe("CodexDiscoveryModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseCodexDiscoveryListQuery.mockReturnValue(
      createQueryResult() as ReturnType<typeof useCodexDiscoveryListQuery>,
    );
    mockedUseCodexPluginReadQuery.mockReturnValue(
      createQueryResult() as ReturnType<typeof useCodexPluginReadQuery>,
    );
  });

  it("renders a non-consumable status message without browse content", async () => {
    const tree = await renderModal({
      codexDiscoveryStatus: "declared_not_consumed",
      availableTabs: [],
      canReadPlugins: false,
    });

    const textNodes = tree.root.findAll(
      (node) =>
        node.props?.children ===
        "This agent declares Codex discovery, but Hub does not currently expose a consumable frontend entry for it.",
    );

    expect(textNodes.length).toBeGreaterThan(0);
    act(() => {
      tree.unmount();
    });
  });

  it("renders plugin detail preview instead of dumping raw JSON", async () => {
    mockedUseCodexDiscoveryListQuery.mockImplementation(
      (input) =>
        createQueryResult(
          input.kind === "plugins"
            ? {
                data: {
                  items: [
                    {
                      marketplaceName: "test",
                      marketplacePath:
                        "/workspace/.codex/plugins/marketplace.json",
                      interface: null,
                      plugins: [
                        {
                          name: "Planner",
                          description: "Coordinates work.",
                          enabled: true,
                          interface: null,
                          mentionPath: "plugin://planner@test",
                          codex: { version: "1.0" },
                        },
                      ],
                      codex: {},
                    },
                  ],
                },
              }
            : {},
        ) as ReturnType<typeof useCodexDiscoveryListQuery>,
    );
    mockedUseCodexPluginReadQuery.mockReturnValue(
      createQueryResult({
        data: {
          item: {
            name: "Planner",
            marketplaceName: "test",
            marketplacePath: "/workspace/.codex/plugins/marketplace.json",
            mentionPath: "plugin://planner@test",
            summary: ["Use for planning"],
            skills: [],
            apps: [],
            mcpServers: [],
            interface: null,
            codex: { version: "1.0" },
          },
        },
      }) as ReturnType<typeof useCodexPluginReadQuery>,
    );

    const tree = await renderModal();

    const pluginButton = tree.root.find(
      (node) => node.props?.accessibilityLabel === "Open Planner",
    );

    await act(async () => {
      pluginButton.props.onPress();
    });

    const detailNodes = tree.root.findAll(
      (node) => node.props?.children === "Use for planning",
    );
    expect(detailNodes.length).toBeGreaterThan(0);

    act(() => {
      tree.unmount();
    });
  });
});
