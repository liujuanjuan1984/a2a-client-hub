import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";

import { useShortcutsQuery } from "../useShortcutsQuery";

import { listShortcuts } from "@/lib/api/shortcuts";

jest.mock("@/lib/api/shortcuts", () => ({
  listShortcuts: jest.fn(),
  createShortcut: jest.fn(),
  updateShortcut: jest.fn(),
  deleteShortcut: jest.fn(),
}));

describe("useShortcutsQuery", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    jest.clearAllMocks();
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("should return sorted shortcuts for agent (agent specific first, system last)", async () => {
    (listShortcuts as jest.Mock).mockResolvedValue([
      {
        id: "custom-system-1",
        title: "Custom System",
        prompt: "System prompt",
        is_default: false,
        order: 10,
        agent_id: null,
      },
      {
        id: "agent-1-shortcut",
        title: "Agent 1 Shortcut",
        prompt: "Agent 1 prompt",
        is_default: false,
        order: 5,
        agent_id: "agent-1",
      },
      {
        id: "agent-2-shortcut",
        title: "Agent 2 Shortcut",
        prompt: "Agent 2 prompt",
        is_default: false,
        order: 6,
        agent_id: "agent-2",
      },
    ]);

    const { result } = renderHook(() => useShortcutsQuery(), { wrapper });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const agent1Shortcuts = result.current.getShortcutsForAgent("agent-1");

    // Agent 1 shortcut should be at the top
    expect(agent1Shortcuts[0].id).toBe("agent-1-shortcut");
    // Followed by system shortcuts (custom-system-1 or default ones)
    // We expect agent-2-shortcut NOT to be in the list
    expect(
      agent1Shortcuts.find((s) => s.id === "agent-2-shortcut"),
    ).toBeUndefined();

    // Verify that all items except the first one have agentId === null
    const rest = agent1Shortcuts.slice(1);
    expect(rest.every((s) => s.agentId === null)).toBe(true);

    // Default agentId null query
    const globalShortcuts = result.current.getShortcutsForAgent(null);
    expect(globalShortcuts.every((s) => s.agentId === null)).toBe(true);
  });

  it("preserves the original order within agent-specific and system shortcut groups", async () => {
    (listShortcuts as jest.Mock).mockResolvedValue([
      {
        id: "system-b",
        title: "System B",
        prompt: "System prompt B",
        is_default: false,
        order: 11,
        agent_id: null,
      },
      {
        id: "agent-1-b",
        title: "Agent 1 B",
        prompt: "Agent 1 prompt B",
        is_default: false,
        order: 8,
        agent_id: "agent-1",
      },
      {
        id: "agent-1-a",
        title: "Agent 1 A",
        prompt: "Agent 1 prompt A",
        is_default: false,
        order: 2,
        agent_id: "agent-1",
      },
      {
        id: "system-a",
        title: "System A",
        prompt: "System prompt A",
        is_default: false,
        order: 1,
        agent_id: null,
      },
    ]);

    const { result } = renderHook(() => useShortcutsQuery(), { wrapper });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const agent1Shortcuts = result.current.getShortcutsForAgent("agent-1");

    expect(agent1Shortcuts.map((shortcut) => shortcut.id)).toEqual([
      "agent-1-a",
      "agent-1-b",
      "11111111-1111-1111-1111-111111111111",
      "22222222-2222-2222-2222-222222222222",
      "system-a",
      "33333333-3333-3333-3333-333333333333",
      "44444444-4444-4444-4444-444444444444",
      "55555555-5555-5555-5555-555555555555",
      "system-b",
    ]);
  });
});
